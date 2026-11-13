import AVFoundation
import Foundation
import MediaPlayer
import SwiftUI

/// App state: the open book, the reading position, playback and settings.
@MainActor
final class ReaderModel: ObservableObject {
    @Published private(set) var document: BookDocument?
    @Published private(set) var current = 0
    @Published private(set) var isPlaying = false
    @Published private(set) var isBuffering = false
    @Published private(set) var engineReady = false
    @Published var status = "Завантаження моделі мовлення…"
    @Published var errorMessage: String?
    /// A scanned PDF waiting for the user to choose the OCR language.
    @Published var ocrPrompt: OCRPrompt?
    @Published private(set) var ocrProgress: (done: Int, total: Int)?
    @Published private(set) var isLoading = false

    @AppStorage("language") var language = "auto" { didSet { applyVoice() } }
    @AppStorage("voice") var voice = "F1" { didSet { applyVoice() } }
    @AppStorage("speed") var speed = 1.0 { didSet { pipeline.rate = Float(speed); updateNowPlaying() } }
    @AppStorage("fontSize") var fontSize = 22.0
    @AppStorage("lastBook") private var lastBook = ""

    struct OCRPrompt: Identifiable {
        let id = UUID()
        let url: URL
        let pages: Int
        let recognizedLanguage: String?
    }

    private let pipeline = SpeechPipeline()
    private var bookURL: URL?
    private var ocrLanguage: String?
    private let loadCancelled = CancelFlag()

    static let booksDirectory: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Books")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    init() {
        pipeline.rate = Float(speed)
        pipeline.onUnitStarted = { [weak self] index in self?.unitStarted(index) }
        pipeline.onFinished = { [weak self] in
            self?.isPlaying = false
            self?.status = "Книжку дочитано"
            self?.updateNowPlaying()
        }
        pipeline.onBuffering = { [weak self] buffering in self?.isBuffering = buffering }
        pipeline.onError = { [weak self] message in self?.status = message }
        setUpRemoteCommands()
        loadEngine()
        if !lastBook.isEmpty {
            let url = Self.booksDirectory.appendingPathComponent(lastBook)
            if FileManager.default.fileExists(atPath: url.path) { open(url) }
        }
    }

    var resolvedLanguage: String {
        language == "auto" ? (document?.language ?? "uk") : language
    }

    var progressText: String {
        guard let document, !document.units.isEmpty else { return "" }
        let percent = Double(current + 1) / Double(document.units.count) * 100
        return "Речення \(current + 1) з \(document.units.count) · \(String(format: "%.1f", percent))%"
    }

    var currentRange: NSRange? {
        guard let document, current < document.units.count else { return nil }
        return document.units[current].range
    }

    // MARK: engine

    private func loadEngine() {
        let pipeline = self.pipeline
        Task.detached(priority: .userInitiated) {
            do {
                guard let onnx = Bundle.main.url(forResource: "onnx", withExtension: nil),
                      let voices = Bundle.main.url(forResource: "voice_styles", withExtension: nil)
                else { throw SpeechError.modelMissing("модель не додано до застосунку") }
                let engine = try SupertonicEngine(onnxDir: onnx, voiceDir: voices)
                pipeline.setEngine(engine)
                await MainActor.run {
                    self.engineReady = true
                    self.status = self.document == nil ? "Відкрийте книжку (TXT або PDF)" : "Готово до читання"
                    self.applyVoice()
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("-autoplay") { self.play() }
                    #endif
                }
            } catch {
                await MainActor.run { self.status = error.localizedDescription }
            }
        }
    }

    private func applyVoice() {
        pipeline.setVoice(language: resolvedLanguage, voice: voice)
    }

    // MARK: books

    /// A file picked in the Files app is copied into the app, so it stays available.
    func importFile(_ url: URL) {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let target = Self.booksDirectory.appendingPathComponent(url.lastPathComponent)
        do {
            if FileManager.default.fileExists(atPath: target.path) { try FileManager.default.removeItem(at: target) }
            try FileManager.default.copyItem(at: url, to: target)
            open(target)
        } catch {
            errorMessage = "Не вдалося відкрити файл: \(error.localizedDescription)"
        }
    }

    /// `ocrLanguage`: nil — as saved for this book (scanned pages are recognized in that language).
    func open(_ url: URL, ocrLanguage requested: String? = nil) {
        guard !isLoading else { return }
        pause()
        savePosition()
        let key = url.lastPathComponent
        let ocrLanguage = requested ?? UserDefaults.standard.string(forKey: "ocr.\(key)")
        isLoading = true
        loadCancelled.reset()
        ocrProgress = nil
        status = "Відкриття «\(url.deletingPathExtension().lastPathComponent)»…"
        let cancel = loadCancelled
        Task.detached(priority: .userInitiated) {
            do {
                let document = try DocumentLoader.load(url, ocrLanguage: ocrLanguage, progress: { done, total in
                    Task { @MainActor in self.ocrProgress = (done, total) }
                }, isCancelled: { cancel.isSet })
                await MainActor.run { self.loaded(document, url: url, ocrLanguage: ocrLanguage) }
            } catch DocumentError.scanned(let pages) {
                await MainActor.run {
                    self.isLoading = false
                    self.status = "Скан без текстового шару"
                    self.ocrPrompt = OCRPrompt(url: url, pages: pages, recognizedLanguage: nil)
                }
            } catch {
                let cancelled = (error as? DocumentError)?.isCancelled == true
                let message = error.localizedDescription
                await MainActor.run {
                    self.isLoading = false
                    self.ocrProgress = nil
                    self.status = cancelled ? "Розпізнавання скасовано (розпізнані сторінки збережено)"
                                            : "Не вдалося відкрити документ"
                    if !cancelled { self.errorMessage = message }
                }
            }
        }
    }

    func cancelLoading() { loadCancelled.set() }

    /// "Recognize again" for the open PDF (e.g. in another language).
    func offerOCR() {
        guard let bookURL, bookURL.pathExtension.lowercased() == "pdf", let document else { return }
        ocrPrompt = OCRPrompt(url: bookURL, pages: max(document.scannedPages, document.recognizedPages),
                              recognizedLanguage: ocrLanguage)
    }

    private func loaded(_ document: BookDocument, url: URL, ocrLanguage: String?) {
        isLoading = false
        ocrProgress = nil
        self.document = document
        bookURL = url
        self.ocrLanguage = document.recognizedPages > 0 ? ocrLanguage : nil
        let key = url.lastPathComponent
        lastBook = key
        if let ocrLanguage, document.recognizedPages > 0 {
            UserDefaults.standard.set(ocrLanguage, forKey: "ocr.\(key)")
        }
        let saved = UserDefaults.standard.integer(forKey: "position.\(key)")
        current = min(max(saved, 0), max(document.units.count - 1, 0))
        pipeline.setUnits(document.units, start: current)
        applyVoice()
        var parts = ["\(document.units.count) речень"]
        if document.recognizedPages > 0, let ocrLanguage {
            parts.append("розпізнано OCR: \(document.recognizedPages) стор., мова: \(ocrLanguage == "ru" ? "Русский" : "Українська")")
        }
        if document.scannedPages > 0 { parts.append("сторінок без тексту: \(document.scannedPages)") }
        if current > 0 { parts.append("продовжуємо з речення \(current + 1)") }
        status = parts.joined(separator: " · ")
        updateNowPlaying()
    }

    // MARK: transport

    func togglePlay() { isPlaying ? pause() : play() }

    func play() {
        guard engineReady, let document, !document.units.isEmpty else { return }
        if current >= document.units.count - 1 && status == "Книжку дочитано" { current = 0 }
        isPlaying = true
        pipeline.play(from: current)
        updateNowPlaying()
    }

    func pause() {
        guard isPlaying else { return }
        isPlaying = false
        isBuffering = false
        pipeline.pause()
        savePosition()
        updateNowPlaying()
    }

    func seek(to index: Int) {
        guard let document, !document.units.isEmpty else { return }
        current = min(max(index, 0), document.units.count - 1)
        pipeline.seek(to: current)
        savePosition()
    }

    func nextSentence() { seek(to: current + 1) }
    func previousSentence() { seek(to: current - 1) }

    /// The reading unit containing a character of the text (a tap on the text).
    func seek(toCharacter offset: Int) {
        guard let units = document?.units, !units.isEmpty else { return }
        var low = 0, high = units.count - 1
        while low < high {
            let mid = (low + high + 1) / 2
            if units[mid].range.location <= offset { low = mid } else { high = mid - 1 }
        }
        seek(to: low)
    }

    private func unitStarted(_ index: Int) {
        current = index
        if index % 5 == 0 { savePosition() }
        updateNowPlaying()
    }

    func savePosition() {
        guard let bookURL else { return }
        UserDefaults.standard.set(current, forKey: "position.\(bookURL.lastPathComponent)")
    }

    // MARK: lock screen / headphones

    private func setUpRemoteCommands() {
        let center = MPRemoteCommandCenter.shared()
        center.playCommand.addTarget { [weak self] _ in self?.play(); return .success }
        center.pauseCommand.addTarget { [weak self] _ in self?.pause(); return .success }
        center.togglePlayPauseCommand.addTarget { [weak self] _ in self?.togglePlay(); return .success }
        center.nextTrackCommand.addTarget { [weak self] _ in self?.nextSentence(); return .success }
        center.previousTrackCommand.addTarget { [weak self] _ in self?.previousSentence(); return .success }
    }

    private func updateNowPlaying() {
        guard let document else { MPNowPlayingInfoCenter.default().nowPlayingInfo = nil; return }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: document.title,
            MPMediaItemPropertyArtist: progressText,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? speed : 0,
        ]
    }
}

extension DocumentError {
    var isCancelled: Bool { if case .cancelled = self { return true } else { return false } }
}

/// A flag set on the main thread and read by a background task.
final class CancelFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false
    var isSet: Bool { lock.withLock { value } }
    func set() { lock.withLock { value = true } }
    func reset() { lock.withLock { value = false } }
}
