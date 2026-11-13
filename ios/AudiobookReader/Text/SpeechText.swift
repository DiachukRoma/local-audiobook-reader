import Foundation

/// Text sent to the speech model: numbers are spelled out in Ukrainian or Russian
/// (Supertonic reads digits unreliably). A reduced port of `tts/text_prep.py`:
/// cardinal numbers in the nominative case only.
enum SpeechText {
    static func prepare(_ text: String, language: String) -> String {
        var result = text.replacingOccurrences(of: "№", with: language == "ru" ? " номер " : " номер ")
        result = result.replacingOccurrences(of: "%", with: language == "ru" ? " процентов" : " відсотків")
        // "10 000" / "10 000" -> "10000"
        result = result.replacingOccurrences(of: #"(?<=\d)[ \u{00A0}\u{202F}](?=\d{3}\b)"#, with: "",
                                             options: .regularExpression)
        let regex = try! NSRegularExpression(pattern: #"\d{1,12}"#)
        let ns = result as NSString
        var out = ""
        var last = 0
        for match in regex.matches(in: result, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: last, length: match.range.location - last))
            let digits = ns.substring(with: match.range)
            out += Int(digits).map { NumberWords.cardinal($0, language: language) } ?? digits
            last = match.range.location + match.range.length
        }
        out += ns.substring(from: last)
        return out.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
    }
}

enum NumberWords {
    private struct Words {
        let units: [String], unitsFeminine: [String], teens: [String], tens: [String], hundreds: [String]
        let zero: String
        let scales: [[String]]  // [one, few, many] for thousand, million, billion
    }

    private static let uk = Words(
        units: ["", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять"],
        unitsFeminine: ["", "одна", "дві", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять"],
        teens: ["десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять",
                "шістнадцять", "сімнадцять", "вісімнадцять", "дев'ятнадцять"],
        tens: ["", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят", "сімдесят", "вісімдесят",
               "дев'яносто"],
        hundreds: ["", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот", "вісімсот",
                   "дев'ятсот"],
        zero: "нуль",
        scales: [["тисяча", "тисячі", "тисяч"], ["мільйон", "мільйони", "мільйонів"],
                 ["мільярд", "мільярди", "мільярдів"]])

    private static let ru = Words(
        units: ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
        unitsFeminine: ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"],
        teens: ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
                "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"],
        tens: ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят",
               "девяносто"],
        hundreds: ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот",
                   "девятьсот"],
        zero: "ноль",
        scales: [["тысяча", "тысячи", "тысяч"], ["миллион", "миллиона", "миллионов"],
                 ["миллиард", "миллиарда", "миллиардов"]])

    /// 0 ... 999 999 999 999 in words (nominative case).
    static func cardinal(_ number: Int, language: String) -> String {
        let w = language == "ru" ? ru : uk
        if number == 0 { return w.zero }
        guard number > 0, number < 1_000_000_000_000 else { return String(number) }
        var parts: [String] = []
        let groups = [number / 1_000_000_000 % 1000, number / 1_000_000 % 1000, number / 1000 % 1000, number % 1000]
        for (index, group) in groups.enumerated() where group > 0 {
            let scale = 3 - index  // 3: billions, 2: millions, 1: thousands, 0: units
            parts.append(triple(group, feminine: scale == 1, words: w))
            if scale > 0 { parts.append(w.scales[scale - 1][pluralForm(group)]) }
        }
        return parts.joined(separator: " ")
    }

    private static func triple(_ n: Int, feminine: Bool, words w: Words) -> String {
        var parts: [String] = []
        if n / 100 > 0 { parts.append(w.hundreds[n / 100]) }
        let rest = n % 100
        if rest >= 10 && rest < 20 {
            parts.append(w.teens[rest - 10])
        } else {
            if rest / 10 > 0 { parts.append(w.tens[rest / 10]) }
            if rest % 10 > 0 { parts.append((feminine ? w.unitsFeminine : w.units)[rest % 10]) }
        }
        return parts.joined(separator: " ")
    }

    /// 0: "одна тисяча", 1: "дві тисячі", 2: "п'ять тисяч".
    static func pluralForm(_ n: Int) -> Int {
        if n % 10 == 1 && n % 100 != 11 { return 0 }
        if (2...4).contains(n % 10) && !(12...14).contains(n % 100) { return 1 }
        return 2
    }
}
