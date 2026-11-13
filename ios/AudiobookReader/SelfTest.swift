#if DEBUG
import Foundation

/// Debug only: `-selftest` at launch synthesizes test sentences and writes ids, durations and WAVs
/// into the app's Documents folder, to compare the Swift port with the Python SDK.
enum SelfTest {
    static func runIfRequested() {
        guard ProcessInfo.processInfo.arguments.contains("-selftest") else { return }
        Task.detached {
            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            var report: [[String: Any]] = []
            do {
                let engine = try SupertonicEngine(onnxDir: Bundle.main.url(forResource: "onnx", withExtension: nil)!,
                                                  voiceDir: Bundle.main.url(forResource: "voice_styles", withExtension: nil)!)
                let cases = [("uk", "Добрий день! Це перевірка синтезу мовлення на планшеті, 2026 рік."),
                             ("ru", "Ёжик пришёл домой, и всё было тёмное.")]
                for (index, (language, text)) in cases.enumerated() {
                    let prepared = SpeechText.prepare(text, language: language)
                    let start = Date()
                    let audio = try engine.synthesize(prepared, language: language, voice: "F1")
                    let elapsed = Date().timeIntervalSince(start)
                    let rms = (audio.reduce(0) { $0 + $1 * $1 } / Float(max(audio.count, 1))).squareRoot()
                    try wav(audio, rate: engine.sampleRate).write(to: docs.appendingPathComponent("selftest-\(index).wav"))
                    report.append(["language": language, "prepared": prepared,
                                   "ids": engine.textIDs(prepared, language: language),
                                   "seconds": Double(audio.count) / Double(engine.sampleRate),
                                   "synthesis_seconds": elapsed, "rms": Double(rms)])
                }
                let doc = DocumentLoader.build(title: "t", paragraphs: [
                    "Т. Шевченко народився 1814 р. у селі Моринці. Див. с. 5. Він — поет!", "Другий абзац."],
                    scanned: 0, recognized: 0)
                report.append(["units": doc.units.map { [$0.text, NSStringFromRange($0.range)] }, "text": doc.text])
            } catch {
                report.append(["error": error.localizedDescription])
            }
            let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted])
            try? data?.write(to: docs.appendingPathComponent("selftest.json"))
        }
    }

    private static func wav(_ samples: [Float], rate: Int) -> Data {
        var data = Data()
        func append<T>(_ value: T) { withUnsafeBytes(of: value) { data.append(contentsOf: $0) } }
        let pcm = samples.map { Int16(max(-1, min(1, $0)) * 32767) }
        data.append("RIFF".data(using: .ascii)!); append(UInt32(36 + pcm.count * 2))
        data.append("WAVEfmt ".data(using: .ascii)!); append(UInt32(16)); append(UInt16(1)); append(UInt16(1))
        append(UInt32(rate)); append(UInt32(rate * 2)); append(UInt16(2)); append(UInt16(16))
        data.append("data".data(using: .ascii)!); append(UInt32(pcm.count * 2))
        pcm.forEach { append($0.littleEndian) }
        return data
    }
}
#endif
