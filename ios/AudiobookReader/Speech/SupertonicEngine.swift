import Foundation
import OnnxRuntimeBindings

enum SpeechError: LocalizedError {
    case modelMissing(String)
    case runtime(String)

    var errorDescription: String? {
        switch self {
        case .modelMissing(let detail): return "Модель Supertonic 3 не знайдено: \(detail)"
        case .runtime(let detail): return "Помилка синтезу: \(detail)"
        }
    }
}

/// Supertonic 3 (Supertone, OpenRAIL-M) on ONNX Runtime: a Swift port of the `supertonic` Python SDK
/// (`core.py`: UnicodeProcessor + Supertonic.__call__). Not thread-safe: use from one queue.
final class SupertonicEngine {
    static let voices = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]

    let sampleRate: Int
    private let baseChunkSize: Int
    private let chunkCompressFactor: Int
    private let latentDim: Int
    private let indexer: [Int]
    private let env: ORTEnv
    private let durationPredictor: ORTSession
    private let textEncoder: ORTSession
    private let vectorEstimator: ORTSession
    private let vocoder: ORTSession
    private let voiceDir: URL
    private var styles: [String: (ttl: [Float], ttlShape: [Int], dp: [Float], dpShape: [Int])] = [:]
    var steps = 8

    init(onnxDir: URL, voiceDir: URL, threads: Int = 4) throws {
        self.voiceDir = voiceDir
        func load(_ name: String) throws -> Data {
            do { return try Data(contentsOf: onnxDir.appendingPathComponent(name)) } catch {
                throw SpeechError.modelMissing(name)
            }
        }
        guard let config = try JSONSerialization.jsonObject(with: load("tts.json")) as? [String: Any],
              let ae = config["ae"] as? [String: Any], let ttl = config["ttl"] as? [String: Any],
              let sampleRate = ae["sample_rate"] as? Int, let baseChunk = ae["base_chunk_size"] as? Int,
              let compress = ttl["chunk_compress_factor"] as? Int, let latentDim = ttl["latent_dim"] as? Int
        else { throw SpeechError.modelMissing("tts.json") }
        self.sampleRate = sampleRate
        self.baseChunkSize = baseChunk
        self.chunkCompressFactor = compress
        self.latentDim = latentDim
        guard let indexer = try JSONSerialization.jsonObject(with: load("unicode_indexer.json")) as? [Int] else {
            throw SpeechError.modelMissing("unicode_indexer.json")
        }
        self.indexer = indexer

        let env = try ORTEnv(loggingLevel: .warning)
        self.env = env
        let options = try ORTSessionOptions()
        try options.setIntraOpNumThreads(Int32(threads))
        try options.setGraphOptimizationLevel(.all)
        // Threads sleep between operations instead of spinning: same speed, much less battery.
        try options.addConfigEntry(withKey: "session.intra_op.allow_spinning", value: "0")
        try options.addConfigEntry(withKey: "session.inter_op.allow_spinning", value: "0")
        func session(_ name: String) throws -> ORTSession {
            let path = onnxDir.appendingPathComponent(name).path
            guard FileManager.default.fileExists(atPath: path) else { throw SpeechError.modelMissing(name) }
            return try ORTSession(env: env, modelPath: path, sessionOptions: options)
        }
        durationPredictor = try session("duration_predictor.onnx")
        textEncoder = try session("text_encoder.onnx")
        vectorEstimator = try session("vector_estimator.onnx")
        vocoder = try session("vocoder.onnx")
    }

    /// Mono float samples at `sampleRate` for one sentence, spoken at the model's natural speed.
    func synthesize(_ text: String, language: String, voice: String) throws -> [Float] {
        let ids = textIDs(text, language: language)
        if ids.count <= 2 { return [] }
        let style = try loadStyle(voice)
        let length = ids.count

        let textIDs = try tensor(ids.map { Int64($0) }, shape: [1, length])
        let textMask = try tensor([Float](repeating: 1, count: length), shape: [1, 1, length])
        let styleDP = try tensor(style.dp, shape: style.dpShape)
        let styleTTL = try tensor(style.ttl, shape: style.ttlShape)

        let duration = try floats(run(durationPredictor, ["text_ids": textIDs, "style_dp": styleDP,
                                                          "text_mask": textMask]))[0]
        guard duration.isFinite, duration > 0 else { return [] }
        let textEmbedding = try run(textEncoder, ["text_ids": textIDs, "style_ttl": styleTTL, "text_mask": textMask])

        // Noisy latent of the predicted length (sample_noisy_latent in core.py).
        let wavLength = Double(duration) * Double(sampleRate)
        let chunk = Double(baseChunkSize * chunkCompressFactor)
        let latentLength = max(Int((wavLength + chunk - 1) / chunk), 1)
        let latentChannels = latentDim * chunkCompressFactor
        let validLatent = (Int(wavLength) + Int(chunk) - 1) / Int(chunk)
        var latentMask = [Float](repeating: 0, count: latentLength)
        for i in 0..<min(validLatent, latentLength) { latentMask[i] = 1 }
        var noise = [Float](repeating: 0, count: latentChannels * latentLength)
        for c in 0..<latentChannels {
            for t in 0..<latentLength { noise[c * latentLength + t] = Self.gaussian() * latentMask[t] }
        }
        let latentMaskTensor = try tensor(latentMask, shape: [1, 1, latentLength])
        let totalStep = try tensor([Float(steps)], shape: [1])
        var latent = try tensor(noise, shape: [1, latentChannels, latentLength])
        for step in 0..<steps {
            latent = try run(vectorEstimator, [
                "noisy_latent": latent, "text_emb": textEmbedding, "style_ttl": styleTTL, "text_mask": textMask,
                "latent_mask": latentMaskTensor, "current_step": try tensor([Float(step)], shape: [1]),
                "total_step": totalStep,
            ])
        }
        var wav = try floats(run(vocoder, ["latent": latent]))
        let keep = min(Int(wavLength), wav.count)
        wav.removeSubrange(keep...)
        guard wav.allSatisfy({ $0.isFinite }) else { throw SpeechError.runtime("некоректний аудіосигнал") }
        return Self.trimSilence(wav, sampleRate: sampleRate)
    }

    // MARK: text -> model ids (UnicodeProcessor._preprocess_text)

    private static let symbolReplacements: [(String, String)] = [
        ("\u{2013}", "-"), ("\u{2011}", "-"), ("\u{2014}", "-"), ("\u{00AF}", " "), ("_", " "),
        ("\u{201C}", "\""), ("\u{201D}", "\""), ("\u{2018}", "'"), ("\u{2019}", "'"), ("\u{00B4}", "'"),
        ("`", "'"), ("[", " "), ("]", " "), ("|", " "), ("/", " "), ("#", " "), ("→", " "), ("←", " "),
    ]

    func textIDs(_ raw: String, language: String) -> [Int] {
        var text = raw.decomposedStringWithCompatibilityMapping  // NFKD, as the model was trained
        text = String(text.unicodeScalars.filter { !$0.properties.isEmojiPresentation }.map(Character.init))
        for (old, new) in Self.symbolReplacements { text = text.replacingOccurrences(of: old, with: new) }
        text = text.replacingOccurrences(of: #"[♥☆♡©\\]"#, with: "", options: .regularExpression)
        text = text.replacingOccurrences(of: "@", with: " at ")
        for p in [",", ".", "!", "?", ";", ":", "'"] { text = text.replacingOccurrences(of: " " + p, with: p) }
        text = text.replacingOccurrences(of: #"(["'`])\1+"#, with: "$1", options: .regularExpression)
        // Characters the model has no index for are dropped instead of failing (as on the desktop).
        text = String(text.unicodeScalars.map { scalar -> Character in
            let v = Int(scalar.value)
            return v < indexer.count && indexer[v] >= 0 ? Character(scalar) : " "
        })
        text = text.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        if text.range(of: #"[.!?;:,'"')\]}…。」』】〉》›»]$"#, options: .regularExpression) == nil { text += "." }
        text = "<\(language)>\(text)</\(language)>"
        return text.unicodeScalars.map { scalar in
            let v = Int(scalar.value)
            return v < indexer.count ? max(indexer[v], 0) : 0
        }
    }

    // MARK: helpers

    private func loadStyle(_ voice: String) throws -> (ttl: [Float], ttlShape: [Int], dp: [Float], dpShape: [Int]) {
        if let style = styles[voice] { return style }
        let url = voiceDir.appendingPathComponent("\(voice).json")
        guard let data = try? Data(contentsOf: url),
              let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let ttl = json["style_ttl"] as? [String: Any], let dp = json["style_dp"] as? [String: Any],
              let ttlDims = ttl["dims"] as? [Int], let dpDims = dp["dims"] as? [Int]
        else { throw SpeechError.modelMissing("voice_styles/\(voice).json") }
        func flatten(_ value: Any?) -> [Float] {
            if let number = value as? NSNumber { return [number.floatValue] }
            if let array = value as? [Any] { return array.flatMap { flatten($0) } }
            return []
        }
        let style = (flatten(ttl["data"]), ttlDims, flatten(dp["data"]), dpDims)
        styles[voice] = style
        return style
    }

    private func tensor<T>(_ values: [T], shape: [Int]) throws -> ORTValue {
        let data = values.withUnsafeBufferPointer { NSMutableData(bytes: $0.baseAddress, length: $0.count * MemoryLayout<T>.stride) }
        let type: ORTTensorElementDataType = T.self == Int64.self ? .int64 : .float
        return try ORTValue(tensorData: data, elementType: type, shape: shape.map { NSNumber(value: $0) })
    }

    private func run(_ session: ORTSession, _ inputs: [String: ORTValue]) throws -> ORTValue {
        let names = try session.outputNames()
        guard let first = names.first else { throw SpeechError.runtime("модель без виходів") }
        let outputs = try session.run(withInputs: inputs, outputNames: [first], runOptions: nil)
        guard let value = outputs[first] else { throw SpeechError.runtime("немає виходу \(first)") }
        return value
    }

    private func floats(_ value: ORTValue) throws -> [Float] {
        let data = try value.tensorData() as Data
        return data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
    }

    private static func gaussian() -> Float {
        // Box–Muller
        let u1 = Float.random(in: Float.ulpOfOne..<1), u2 = Float.random(in: 0..<1)
        return (-2 * log(u1)).squareRoot() * cos(2 * .pi * u2)
    }

    /// Leading/trailing near-silence removed, with a short natural margin (as `trim_silence` on the desktop).
    static func trimSilence(_ audio: [Float], sampleRate: Int, threshold: Float = 0.008) -> [Float] {
        guard let first = audio.firstIndex(where: { abs($0) > threshold }),
              let last = audio.lastIndex(where: { abs($0) > threshold }) else { return [] }
        let margin = Int(0.04 * Double(sampleRate))
        return Array(audio[max(first - margin, 0)..<min(last + margin, audio.count)])
    }
}
