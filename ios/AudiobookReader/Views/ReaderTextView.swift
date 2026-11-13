import SwiftUI
import UIKit

/// The whole book as one text. The sentence being read is highlighted and kept in view;
/// a tap on the text moves the reading position to the tapped sentence.
struct ReaderTextView: UIViewRepresentable {
    let text: String
    let highlight: NSRange?
    let fontSize: CGFloat
    let onTap: (Int) -> Void

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isSelectable = false
        view.backgroundColor = .systemBackground
        view.textContainerInset = UIEdgeInsets(top: 24, left: 32, bottom: 120, right: 32)
        view.alwaysBounceVertical = true
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tapped(_:)))
        view.addGestureRecognizer(tap)
        context.coordinator.textView = view
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        let coordinator = context.coordinator
        coordinator.onTap = onTap
        if coordinator.text != text || coordinator.fontSize != fontSize {
            let style = NSMutableParagraphStyle()
            style.lineSpacing = fontSize * 0.35
            style.paragraphSpacing = fontSize * 0.6
            view.attributedText = NSAttributedString(string: text, attributes: [
                .font: UIFont(name: "Georgia", size: fontSize) ?? UIFont.systemFont(ofSize: fontSize),
                .foregroundColor: UIColor.label,
                .paragraphStyle: style,
            ])
            coordinator.text = text
            coordinator.fontSize = fontSize
            coordinator.highlighted = nil
        }
        if coordinator.highlighted != highlight {
            let storage = view.textStorage
            if let old = coordinator.highlighted, NSMaxRange(old) <= storage.length {
                storage.removeAttribute(.backgroundColor, range: old)
            }
            if let range = highlight, NSMaxRange(range) <= storage.length {
                storage.addAttribute(.backgroundColor, value: UIColor.systemYellow.withAlphaComponent(0.35), range: range)
            }
            coordinator.highlighted = highlight
            if let range = highlight { DispatchQueue.main.async { coordinator.scrollIntoView(range) } }
        }
    }

    final class Coordinator: NSObject {
        weak var textView: UITextView?
        var text = ""
        var fontSize: CGFloat = 0
        var highlighted: NSRange?
        var onTap: (Int) -> Void = { _ in }

        @objc func tapped(_ gesture: UITapGestureRecognizer) {
            guard let view = textView else { return }
            let point = gesture.location(in: view)
            guard let position = view.closestPosition(to: point) else { return }
            onTap(view.offset(from: view.beginningOfDocument, to: position))
        }

        /// Scroll so the sentence sits a quarter of the way down; nothing moves while it is in view.
        func scrollIntoView(_ range: NSRange) {
            guard let view = textView,
                  let start = view.position(from: view.beginningOfDocument, offset: range.location),
                  let end = view.position(from: start, offset: range.length),
                  let textRange = view.textRange(from: start, to: end) else { return }
            let rects = view.selectionRects(for: textRange).map(\.rect).filter { !$0.isEmpty }
            guard let first = rects.first else { return }
            let bottom = rects.map(\.maxY).max() ?? first.maxY
            let visible = view.bounds.inset(by: view.adjustedContentInset)
            if first.minY >= visible.minY && bottom <= visible.maxY { return }
            let height = view.bounds.height - view.adjustedContentInset.top - view.adjustedContentInset.bottom
            let maxOffset = max(view.contentSize.height - view.bounds.height + view.adjustedContentInset.bottom,
                                -view.adjustedContentInset.top)
            let target = min(max(first.minY - height / 4 - view.adjustedContentInset.top, -view.adjustedContentInset.top),
                             maxOffset)
            view.setContentOffset(CGPoint(x: 0, y: target), animated: true)
        }
    }
}
