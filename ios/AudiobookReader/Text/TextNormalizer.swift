import Foundation

/// Whitespace and typography cleanup that keeps the meaning of the text
/// (a port of `document/normalize.py`).
enum TextNormalizer {
    private static let invisible = CharacterSet(charactersIn: "\u{00AD}\u{200B}\u{200C}\u{200D}\u{2060}\u{FEFF}")

    /// One paragraph: unify whitespace and rejoin words hyphenated at line ends.
    static func paragraph(_ raw: String) -> String {
        var text = raw.precomposedStringWithCanonicalMapping
        text = String(text.unicodeScalars.filter { !invisible.contains($0) }.map(Character.init))
        text = text.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
        // "сло-\nво" -> "слово" (only when the next line starts with a lowercase letter)
        text = text.replacingOccurrences(of: #"(\w)[-‐]\s*\n\s*(?=[a-zа-яіїєґё])"#, with: "$1",
                                         options: .regularExpression)
        text = text.replacingOccurrences(of: #"\s*\n\s*"#, with: " ", options: .regularExpression)
        text = text.replacingOccurrences(of: #"[ \t\u{00A0}\u{2000}-\u{200A}\u{202F}\u{205F}\u{3000}]+"#, with: " ",
                                         options: .regularExpression)
        text = text.replacingOccurrences(of: #" +([,.;:!?»)\]])"#, with: "$1", options: .regularExpression)
        text = text.replacingOccurrences(of: #"([«(\[]) +"#, with: "$1", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func isReadable(_ text: String) -> Bool {
        text.contains { $0.isLetter || $0.isNumber }
    }

    /// "uk", "ru" or nil, from letters specific to each language.
    static func detectLanguage(_ text: String) -> String? {
        var uk = 0, ru = 0, cyrillic = 0
        for scalar in text.lowercased().unicodeScalars.prefix(200_000) {
            switch scalar {
            case "і", "ї", "є", "ґ": uk += 1
            case "ы", "э", "ё", "ъ": ru += 1
            default: break
            }
            if (0x0400...0x04FF).contains(scalar.value) { cyrillic += 1 }
        }
        if cyrillic < 20 { return nil }
        return ru > uk ? "ru" : "uk"
    }
}
