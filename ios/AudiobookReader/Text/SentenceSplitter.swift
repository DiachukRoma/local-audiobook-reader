import Foundation

/// Splits a paragraph into sentences; abbreviations and initials do not end a sentence.
/// A port of `document/chunking.py` (`split_sentences`, `_split_long`).
enum SentenceSplitter {
    static let maxChars = 200

    private static let abbreviations: Set<String> = [
        // Ukrainian
        "т", "д", "п", "ін", "ім", "див", "напр", "вул", "просп", "пров", "м", "р", "рр",
        "ст", "стор", "с", "тис", "млн", "млрд", "грн", "коп", "проф", "акад", "доц", "канд",
        "зав", "вид", "обл", "р-н", "пл", "буд", "кв", "св", "гр", "зб", "т.зв", "зв", "розд",
        "табл", "рис", "мал", "прим", "ред", "упор", "пер", "ч", "кн", "вип", "н", "е",
        // Russian
        "др", "пр", "см", "ул", "г", "гг", "в", "вв", "руб", "тыс", "стр", "гл",
        "изд", "т.е", "т.д", "т.п", "и.о", "им", "наб",
        // Latin
        "mr", "mrs", "ms", "dr", "prof", "vs", "etc", "e.g", "i.e", "no", "vol", "pp",
    ]

    private static let sentenceEnd = try! NSRegularExpression(pattern: #"([.!?…]+[»"”’')\]]*)(\s+)"#)
    private static let finalAbbreviation = try! NSRegularExpression(
        pattern: #"(?:\bт\.\s?(?:д|п|ін|е)|\b(?:др|etc|пр))$"#, options: [.caseInsensitive])
    private static let shortCapitalized = try! NSRegularExpression(pattern: #"(?<![\w'])[A-ZА-ЯЁІЇЄҐ][\w']{0,9}$"#)
    private static let clauseBreak = try! NSRegularExpression(pattern: #"[;:,]\s+|\s[—–-]\s"#)
    private static let closers = CharacterSet(charactersIn: "»\"”’')]")

    /// Sentences of a paragraph; a sentence longer than `maxChars` is split at clause boundaries.
    /// Every piece is a substring of `paragraph`.
    static func segments(_ paragraph: String) -> [String] {
        sentences(paragraph).flatMap { splitLong($0, maxChars: maxChars) }
    }

    static func sentences(_ text: String) -> [String] {
        let ns = text as NSString
        var result: [String] = []
        var start = 0
        for match in sentenceEnd.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            let punctRange = match.range(at: 1)
            let punct = ns.substring(with: punctRange)
            let end = punctRange.location + punctRange.length
            let afterLocation = match.range.location + match.range.length
            let following = afterLocation < ns.length ? ns.substring(with: NSRange(location: afterLocation, length: 1)) : ""
            if start > punctRange.location { continue }
            if punct.hasPrefix("."), punct.trimmingCharacters(in: closers).count == 1 {
                let before = ns.substring(with: NSRange(location: start, length: punctRange.location - start))
                let endsSentence = isUpper(following) && matches(finalAbbreviation, before)
                if !endsSentence && isAbbreviation(before) { continue }
                // "3. 5" or a lowercase continuation is unlikely to be a new sentence.
                if isLower(following) { continue }
                // A short capitalized abbreviation before a number is a reference: "Мт. 5:3".
                if following.first?.isNumber == true && matches(shortCapitalized, before) { continue }
            }
            let sentence = ns.substring(with: NSRange(location: start, length: end - start))
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !sentence.isEmpty { result.append(sentence) }
            start = afterLocation
        }
        let tail = ns.substring(from: start).trimmingCharacters(in: .whitespacesAndNewlines)
        if !tail.isEmpty { result.append(tail) }
        return result
    }

    static func splitLong(_ sentence: String, maxChars: Int) -> [String] {
        if sentence.count <= maxChars { return [sentence] }
        var pieces: [String] = []
        var rest = sentence
        while rest.count > maxChars {
            let window = String(rest.prefix(maxChars + 1))
            let wns = window as NSString
            var cut = -1
            for match in clauseBreak.matches(in: window, range: NSRange(location: 0, length: wns.length))
            where match.range.location >= (wns.length / 3) {
                cut = match.range.location + match.range.length
            }
            let rns = rest as NSString
            if cut <= 0 {
                let lastSpace = wns.range(of: " ", options: .backwards).location
                cut = lastSpace == NSNotFound ? -1 : lastSpace
            }
            if cut <= 0 {
                // One "word" longer than maxChars (a URL): cut at the next space.
                let next = rns.range(of: " ", options: [], range: NSRange(location: wns.length - 1, length: rns.length - wns.length + 1))
                cut = next.location == NSNotFound ? rns.length : next.location
            }
            let piece = rns.substring(to: cut).trimmingCharacters(in: .whitespaces)
            if !piece.isEmpty { pieces.append(piece) }
            rest = rns.substring(from: cut).trimmingCharacters(in: .whitespaces)
        }
        if !rest.isEmpty { pieces.append(rest) }
        return pieces
    }

    // MARK: helpers

    private static func isAbbreviation(_ before: String) -> Bool {
        guard let last = before.split(whereSeparator: { $0.isWhitespace }).last else { return false }
        var word = String(last).lowercased()
        while let first = word.first, "«\"„“(".contains(first) { word.removeFirst() }
        if word.hasSuffix(".") { word.removeLast() }
        if word.count == 1, word.first!.isLetter { return true }  // initials: "Т. Шевченко"
        return abbreviations.contains(word)
    }

    private static func matches(_ regex: NSRegularExpression, _ text: String) -> Bool {
        regex.firstMatch(in: text, range: NSRange(location: 0, length: (text as NSString).length)) != nil
    }

    private static func isUpper(_ s: String) -> Bool { s.first.map { $0.isUppercase } ?? false }
    private static func isLower(_ s: String) -> Bool { s.first.map { $0.isLowercase } ?? false }
}
