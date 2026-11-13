import AVFoundation
import Foundation

/// One unit of reading: a sentence (or a piece of a very long one) and where it is in the text.
struct ReadingUnit {
    let range: NSRange       // UTF-16 range in the document text
    let text: String
    let paragraphEnd: Bool
}

/// Synthesizes sentences ahead of playback on a worker thread and plays them gaplessly.
/// The tempo is changed by AVAudioUnitTimePitch, so a speed change needs no new synthesis.
/// Callbacks arrive on the main queue.
final class SpeechPipeline {
    var onUnitStarted: ((Int) -> Void)?
    var onFinished: (() -> Void)?
    var onBuffering: ((Bool) -> Void)?
    var onError: ((String) -> Void)?

    private let audioEngine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let timePitch = AVAudioUnitTimePitch()
    private var format: AVAudioFormat?

    private let condition = NSCondition()
    // Buffer completions are handled here: AVAudioPlayerNode.stop() may call them synchronously,
    // and it is called while `condition` is held.
    private let callbackQueue = DispatchQueue(label: "speech.completions")
    private var engine: SupertonicEngine?
    private var units: [ReadingUnit] = []
    private var language = "uk"
    private var voice = "F1"
    private var epoch = 0
    private var nextToSynthesize = 0
    private var queued: [Int] = []          // units scheduled on the player, in order
    private var wantsToPlay = false
    private var shutdown = false
    private var cache: [String: [Float]] = [:]
    private var cacheOrder: [String] = []

    static let lookahead = 3
    var sentencePause = 0.2
    var paragraphPause = 0.55

    init() {
        audioEngine.attach(player)
        audioEngine.attach(timePitch)
        Thread { [weak self] in self?.workerLoop() }.start()
    }

    deinit {
        condition.lock(); shutdown = true; condition.broadcast(); condition.unlock()
    }

    // MARK: setup

    func setEngine(_ engine: SupertonicEngine) {
        let format = AVAudioFormat(standardFormatWithSampleRate: Double(engine.sampleRate), channels: 1)!
        self.format = format
        audioEngine.connect(player, to: timePitch, format: format)
        audioEngine.connect(timePitch, to: audioEngine.mainMixerNode, format: format)
        condition.lock(); self.engine = engine; condition.broadcast(); condition.unlock()
    }

    func setUnits(_ units: [ReadingUnit], start: Int) {
        condition.lock()
        self.units = units
        resetLocked(start)
        condition.unlock()
    }

    func setVoice(language: String, voice: String) {
        condition.lock()
        let changed = language != self.language || voice != self.voice
        self.language = language
        self.voice = voice
        if changed { resetLocked(queued.first ?? nextToSynthesize) }
        condition.unlock()
    }

    var rate: Float {
        get { timePitch.rate }
        set { timePitch.rate = min(max(newValue, 0.5), 3.0) }
    }

    // MARK: transport

    func play(from index: Int) {
        condition.lock()
        wantsToPlay = true
        if queued.first != index { resetLocked(index) }
        condition.unlock()
        startAudio()
        DispatchQueue.main.async { self.onUnitStarted?(index) }
    }

    func pause() {
        condition.lock(); wantsToPlay = false; condition.unlock()
        player.pause()
    }

    /// Jump to `index`; playback continues there if it was playing.
    func seek(to index: Int) {
        condition.lock()
        resetLocked(index)
        let playing = wantsToPlay
        condition.unlock()
        if playing { startAudio() }
    }

    // MARK: internals

    private func resetLocked(_ index: Int) {
        epoch += 1
        nextToSynthesize = max(0, min(index, max(units.count - 1, 0)))
        queued.removeAll()
        player.stop()  // completion handlers of old buffers fire with an old epoch and are ignored
        condition.broadcast()
    }

    private func startAudio() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .spokenAudio)
            try session.setActive(true)
            if !audioEngine.isRunning { try audioEngine.start() }
            player.play()
        } catch {
            DispatchQueue.main.async { self.onError?("Не вдалося відкрити аудіовихід: \(error.localizedDescription)") }
        }
    }

    private func workerLoop() {
        while true {
            condition.lock()
            while !shutdown && !(engine != nil && wantsToPlay && nextToSynthesize < units.count
                                 && queued.count < Self.lookahead) {
                condition.wait()
            }
            if shutdown { condition.unlock(); return }
            let epoch = self.epoch, index = nextToSynthesize, unit = units[index]
            let engine = self.engine!, language = self.language, voice = self.voice
            let starving = queued.isEmpty
            condition.unlock()

            if starving { DispatchQueue.main.async { self.onBuffering?(true) } }
            let key = "\(language)|\(voice)|\(unit.text)"
            var samples = cachedAudio(key)
            if samples == nil {
                do {
                    let prepared = SpeechText.prepare(unit.text, language: language)
                    samples = TextNormalizer.isReadable(prepared)
                        ? try engine.synthesize(prepared, language: language, voice: voice) : []
                    storeAudio(key, samples!)
                } catch {
                    let message = error.localizedDescription
                    DispatchQueue.main.async { self.onError?("Речення пропущено. \(message)") }
                    samples = []
                }
            }

            condition.lock()
            if epoch != self.epoch || shutdown { condition.unlock(); continue }
            let pause = unit.paragraphEnd ? paragraphPause : sentencePause
            schedule(samples! + [Float](repeating: 0, count: Int(pause * Double(engine.sampleRate))),
                     index: index, epoch: epoch)
            queued.append(index)
            nextToSynthesize = index + 1
            condition.unlock()
            if starving { DispatchQueue.main.async { self.onBuffering?(false) } }
        }
    }

    private func schedule(_ samples: [Float], index: Int, epoch: Int) {
        guard let format, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(max(samples.count, 1))) else { return }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { source in
            buffer.floatChannelData![0].update(from: source.baseAddress!, count: samples.count)
        }
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            self?.callbackQueue.async { self?.finished(index: index, epoch: epoch) }
        }
    }

    private func finished(index: Int, epoch: Int) {
        condition.lock()
        guard epoch == self.epoch, queued.first == index else { condition.unlock(); return }
        queued.removeFirst()
        let next = index + 1
        let atEnd = next >= units.count
        if atEnd { wantsToPlay = false }
        condition.broadcast()
        condition.unlock()
        DispatchQueue.main.async {
            if atEnd { self.onFinished?() } else { self.onUnitStarted?(next) }
        }
    }

    private func cachedAudio(_ key: String) -> [Float]? {
        condition.lock(); defer { condition.unlock() }
        return cache[key]
    }

    private func storeAudio(_ key: String, _ samples: [Float]) {
        condition.lock(); defer { condition.unlock() }
        cache[key] = samples
        cacheOrder.append(key)
        if cacheOrder.count > 40 { cache[cacheOrder.removeFirst()] = nil }
    }
}
