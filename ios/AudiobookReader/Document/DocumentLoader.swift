import Foundation
import PDFKit
import UIKit
import Vision

/// A book as one continuous text (paragraphs on separate lines) cut into reading units.
struct BookDocument {
    let title: String
    let text: String
    let units: [ReadingUnit]
    let language: String?
    let scannedPages: Int      // pages without a text layer that were not recognized
    let recognizedPages: Int   // pages read by OCR
}

enum DocumentError: LocalizedError {
    case unreadable(String)
    case scanned(pages: Int)
    case cancelled

    var errorDescription: String? {
        switch self {
        case .unreadable(let detail): return detail
        case .scanned(let pages): return "Цей PDF — скан без текстового шару (\(pages) стор.)."
        case .cancelled: return "Скасовано"
        }
    }
}

enum DocumentLoader {
    /// `ocrLanguage`: recognize pages without a text layer in this language ("uk"/"ru"); nil — do not.
    static func load(_ url: URL, ocrLanguage: String? = nil,
                     progress: @escaping (Int, Int) -> Void = { _, _ in },
                     isCancelled: @escaping () -> Bool = { false }) throws -> BookDocument {
        let title = url.deletingPathExtension().lastPathComponent
        switch url.pathExtension.lowercased() {
        case "pdf":
            return try loadPDF(url, title: title, ocrLanguage: ocrLanguage, progress: progress, isCancelled: isCancelled)
        default:
            return build(title: title, paragraphs: try textParagraphs(url), scanned: 0, recognized: 0)
        }
    }

    static func build(title: String, paragraphs raw: [String], scanned: Int, recognized: Int) -> BookDocument {
        let paragraphs = raw.map(TextNormalizer.paragraph).filter(TextNormalizer.isReadable)
        var text = ""
        var units: [ReadingUnit] = []
        for (index, paragraph) in paragraphs.enumerated() {
            if index > 0 { text += "\n" }
            let base = (text as NSString).length
            text += paragraph
            let ns = paragraph as NSString
            var cursor = 0
            let segments = SentenceSplitter.segments(paragraph)
            for (i, segment) in segments.enumerated() {
                let found = ns.range(of: segment, options: [], range: NSRange(location: cursor, length: ns.length - cursor))
                guard found.location != NSNotFound else { continue }
                cursor = found.location + found.length
                units.append(ReadingUnit(range: NSRange(location: base + found.location, length: found.length),
                                         text: segment, paragraphEnd: i == segments.count - 1))
            }
        }
        return BookDocument(title: title, text: text, units: units,
                            language: TextNormalizer.detectLanguage(text), scannedPages: scanned,
                            recognizedPages: recognized)
    }

    // MARK: plain text

    private static func textParagraphs(_ url: URL) throws -> [String] {
        guard let data = try? Data(contentsOf: url) else { throw DocumentError.unreadable("Не вдалося прочитати файл.") }
        let text = String(data: data, encoding: .utf8) ?? String(data: data, encoding: .utf16)
            ?? String(data: data, encoding: .windowsCP1251) ?? String(decoding: data, as: UTF8.self)
        let normalized = text.replacingOccurrences(of: "\r\n", with: "\n")
        let blocks = normalized.components(separatedBy: try! NSRegularExpression(pattern: #"\n[ \t]*\n"#))
        // No blank lines between paragraphs: every line is a paragraph.
        if blocks.count == 1 { return normalized.components(separatedBy: "\n") }
        return blocks
    }

    // MARK: PDF

    private static func loadPDF(_ url: URL, title: String, ocrLanguage: String?,
                                progress: @escaping (Int, Int) -> Void,
                                isCancelled: @escaping () -> Bool) throws -> BookDocument {
        guard let pdf = PDFDocument(url: url) else { throw DocumentError.unreadable("Не вдалося відкрити PDF.") }
        if pdf.isLocked { throw DocumentError.unreadable("PDF захищений паролем.") }
        let pdfTitle = (pdf.documentAttributes?[PDFDocumentAttribute.titleAttribute] as? String)?
            .trimmingCharacters(in: .whitespaces)

        var pageParagraphs: [[String]] = []
        var scanned: [Int] = []
        for index in 0..<pdf.pageCount {
            let string = pdf.page(at: index)?.string ?? ""
            if string.filter({ $0.isLetter }).count < 20 { scanned.append(index) }
            pageParagraphs.append(paragraphsFromTextLayer(string))
        }
        if ocrLanguage == nil && !scanned.isEmpty && scanned.count * 2 > pdf.pageCount {
            throw DocumentError.scanned(pages: scanned.count)
        }
        var recognized = 0
        if let language = ocrLanguage, !scanned.isEmpty {
            let cache = OCRCache(pdf: url, language: language)
            for (done, index) in scanned.enumerated() {
                if isCancelled() { cache.save(); throw DocumentError.cancelled }
                if let cached = cache.pages[index] {
                    pageParagraphs[index] = cached
                } else if let page = pdf.page(at: index) {
                    let paragraphs = try OCR.recognize(page, language: language)
                    pageParagraphs[index] = paragraphs
                    cache.pages[index] = paragraphs
                    if done % 10 == 9 { cache.save() }
                }
                progress(done + 1, scanned.count)
            }
            cache.save()
            recognized = scanned.count
        }
        return build(title: pdfTitle?.isEmpty == false ? pdfTitle! : title, paragraphs: joinPages(pageParagraphs),
                     scanned: ocrLanguage == nil ? scanned.count : 0, recognized: recognized)
    }

    /// Lines of a text layer -> paragraphs: a paragraph ends at a blank line, or after a line that
    /// ends a sentence and is clearly shorter than a full line. Bare page numbers are dropped.
    static func paragraphsFromTextLayer(_ string: String) -> [String] {
        let lines = string.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }
        let lengths = lines.map(\.count).filter { $0 > 0 }.sorted()
        let fullLine = lengths.isEmpty ? 0 : lengths[Int(Double(lengths.count) * 0.8)]
        var paragraphs: [String] = []
        var current: [String] = []
        for line in lines {
            if line.isEmpty || line.allSatisfy(\.isNumber) {
                if line.isEmpty, !current.isEmpty { paragraphs.append(current.joined(separator: "\n")); current = [] }
                continue
            }
            current.append(line)
            let endsSentence = line.last.map { ".!?…»:\"".contains($0) } ?? false
            if endsSentence && Double(line.count) < Double(fullLine) * 0.85 {
                paragraphs.append(current.joined(separator: "\n"))
                current = []
            }
        }
        if !current.isEmpty { paragraphs.append(current.joined(separator: "\n")) }
        return paragraphs
    }

    /// A paragraph that does not end a sentence at the bottom of a page continues on the next one.
    static func joinPages(_ pages: [[String]]) -> [String] {
        var result: [String] = []
        var openEnd = false
        for page in pages {
            for (i, paragraph) in page.enumerated() {
                if i == 0, openEnd, let last = result.popLast() {
                    result.append(last + "\n" + paragraph)
                } else {
                    result.append(paragraph)
                }
            }
            if let last = result.last?.trimmingCharacters(in: .whitespaces).last {
                openEnd = !".!?…»\"".contains(last)
            }
        }
        return result
    }
}

/// Recognized pages of one PDF in one language, kept in Caches so a book is recognized once.
final class OCRCache {
    var pages: [Int: [String]]
    private let file: URL

    init(pdf: URL, language: String) {
        let size = (try? FileManager.default.attributesOfItem(atPath: pdf.path)[.size] as? Int) ?? 0
        let dir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("ocr")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        file = dir.appendingPathComponent("\(pdf.lastPathComponent)-\(size)-\(language).json")
        let stored = (try? Data(contentsOf: file)).flatMap { try? JSONDecoder().decode([String: [String]].self, from: $0) }
        pages = Dictionary(uniqueKeysWithValues: (stored ?? [:]).compactMap { key, value in Int(key).map { ($0, value) } })
    }

    func save() {
        let encoded = Dictionary(uniqueKeysWithValues: pages.map { (String($0.key), $0.value) })
        try? JSONEncoder().encode(encoded).write(to: file, options: .atomic)
    }
}

enum OCR {
    /// Paragraphs of a scanned page, recognized on-device by Apple Vision in one language.
    static func recognize(_ page: PDFPage, language: String) throws -> [String] {
        let box = page.bounds(for: .mediaBox)
        let scale = 2400 / max(box.width, box.height)  // about 300 dpi for A4
        let image = page.thumbnail(of: CGSize(width: box.width * scale, height: box.height * scale), for: .mediaBox)
        guard let cgImage = image.cgImage else { return [] }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = [language == "ru" ? "ru-RU" : "uk-UA"]
        request.usesLanguageCorrection = true
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
        let lines: [OCRLine] = (request.results ?? []).compactMap { observation in
            guard let text = observation.topCandidates(1).first?.string.trimmingCharacters(in: .whitespaces),
                  !text.isEmpty else { return nil }
            let b = observation.boundingBox  // normalized, origin bottom-left
            return OCRLine(top: 1 - b.maxY, bottom: 1 - b.minY, left: b.minX, right: b.maxX, text: text)
        }
        return groupLines(lines.sorted { ($0.top, $0.left) < ($1.top, $1.left) })
    }

    struct OCRLine { let top, bottom, left, right: CGFloat; let text: String }

    /// Lines -> paragraphs (a port of `group_lines` in `document/ocr.py`): a new paragraph starts after a
    /// vertical gap, at an indented line, or after a short line that ends a sentence.
    static func groupLines(_ lines: [OCRLine]) -> [String] {
        guard !lines.isEmpty else { return [] }
        func median(_ values: [CGFloat]) -> CGFloat { values.sorted()[values.count / 2] }
        let lineHeight = median(lines.map { $0.bottom - $0.top })
        let margin = median(lines.map(\.left))
        let rights = lines.map(\.right).sorted()
        let fullRight = rights[Int(Double(rights.count) * 0.8)]
        var paragraphs: [[String]] = []
        var previous: OCRLine?
        for line in lines {
            var isNew = previous == nil
            if let p = previous {
                let gap = line.top - p.bottom
                let indented = line.left - margin > 0.02 && abs(p.left - margin) < 0.015
                let shortPrevious = p.right < fullRight - 0.08
                    && (p.text.last.map { ".!?…»:\"".contains($0) } ?? false)
                isNew = gap > 0.9 * lineHeight || gap < -0.5 * lineHeight || indented || shortPrevious
            }
            if isNew { paragraphs.append([line.text]) } else { paragraphs[paragraphs.count - 1].append(line.text) }
            previous = line
        }
        // A bare page number is not text to read.
        return paragraphs.map { $0.joined(separator: "\n") }.filter { !$0.allSatisfy { $0.isNumber || $0.isWhitespace } }
    }
}

private extension String {
    func components(separatedBy regex: NSRegularExpression) -> [String] {
        let ns = self as NSString
        var parts: [String] = []
        var last = 0
        for match in regex.matches(in: self, range: NSRange(location: 0, length: ns.length)) {
            parts.append(ns.substring(with: NSRange(location: last, length: match.range.location - last)))
            last = match.range.location + match.range.length
        }
        parts.append(ns.substring(from: last))
        return parts
    }
}
