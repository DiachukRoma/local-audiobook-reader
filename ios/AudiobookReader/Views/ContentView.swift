import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject private var model: ReaderModel
    @State private var importing = false

    var body: some View {
        NavigationStack {
            ZStack {
                if let document = model.document {
                    ReaderTextView(text: document.text, highlight: model.currentRange,
                                   fontSize: CGFloat(model.fontSize)) { offset in
                        model.seek(toCharacter: offset)
                    }
                    .ignoresSafeArea(edges: .bottom)
                } else {
                    EmptyLibraryView(importing: $importing)
                }
                if model.isLoading { LoadingOverlay() }
            }
            .navigationTitle(model.document?.title ?? "Аудіокнижка")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbar }
            .safeAreaInset(edge: .bottom) { PlayerBar() }
        }
        .fileImporter(isPresented: $importing,
                      allowedContentTypes: [.pdf, .plainText, .utf8PlainText, .text]) { result in
            if case .success(let url) = result { model.importFile(url) }
        }
        .sheet(item: $model.ocrPrompt) { prompt in OCRSheet(prompt: prompt) }
        .alert("Помилка", isPresented: Binding(get: { model.errorMessage != nil },
                                               set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button { importing = true } label: { Label("Відкрити", systemImage: "folder") }
        }
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Section("Розмір тексту") {
                    Button { model.fontSize = min(model.fontSize + 2, 44) } label: { Label("Більше", systemImage: "textformat.size.larger") }
                    Button { model.fontSize = max(model.fontSize - 2, 14) } label: { Label("Менше", systemImage: "textformat.size.smaller") }
                }
                if model.document != nil {
                    Button { model.offerOCR() } label: { Label("Розпізнати текст (OCR)…", systemImage: "doc.text.viewfinder") }
                }
            } label: {
                Label("Ще", systemImage: "textformat.size")
            }
        }
    }
}

/// Transport, language, voice and speed. On a narrow screen the groups wrap onto a second line.
struct PlayerBar: View {
    @EnvironmentObject private var model: ReaderModel

    var body: some View {
        VStack(spacing: 8) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 24) { transport; Spacer(minLength: 0); voiceControls; speedControl }
                VStack(spacing: 10) {
                    HStack { transport; Spacer(); voiceControls }
                    HStack { speedControl; Spacer() }
                }
            }
            HStack {
                Text(model.status).lineLimit(1)
                Spacer()
                Text(model.progressText).monospacedDigit()
            }
            .font(.footnote)
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.bar)
    }

    private var transport: some View {
        HStack(spacing: 18) {
            Button { model.previousSentence() } label: { Image(systemName: "backward.end.fill") }
                .accessibilityLabel("Попереднє речення")
            Button { model.togglePlay() } label: {
                ZStack {
                    if model.isPlaying && model.isBuffering {
                        ProgressView()
                    } else {
                        Image(systemName: model.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                            .font(.system(size: 44))
                    }
                }
                .frame(width: 48, height: 48)
            }
            .accessibilityLabel(model.isPlaying ? "Пауза" : "Читати")
            Button { model.nextSentence() } label: { Image(systemName: "forward.end.fill") }
                .accessibilityLabel("Наступне речення")
        }
        .font(.title2)
        .disabled(model.document == nil || !model.engineReady)
    }

    private var voiceControls: some View {
        HStack(spacing: 12) {
            Picker("Мова", selection: $model.language) {
                Text("Мова: авто").tag("auto")
                Text("Українська").tag("uk")
                Text("Русский").tag("ru")
            }
            Picker("Голос", selection: $model.voice) {
                ForEach(SupertonicEngine.voices, id: \.self) { voice in
                    Text(voice.hasPrefix("F") ? "Жіночий \(voice.dropFirst())" : "Чоловічий \(voice.dropFirst())")
                        .tag(voice)
                }
            }
        }
        .pickerStyle(.menu)
    }

    private var speedControl: some View {
        HStack(spacing: 10) {
            Image(systemName: "hare").foregroundStyle(.secondary)
            Slider(value: $model.speed, in: 0.7...3.0, step: 0.05).frame(width: 160)
            TextField("", value: $model.speed, format: .number.precision(.fractionLength(2)))
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .textFieldStyle(.roundedBorder)
                .frame(width: 72)
                .onSubmit { model.speed = min(max(model.speed, 0.7), 3.0) }
            Text("×").foregroundStyle(.secondary)
        }
    }
}

struct EmptyLibraryView: View {
    @Binding var importing: Bool

    var body: some View {
        VStack(spacing: 16) {
            Image("Logo").resizable().frame(width: 96, height: 96).clipShape(RoundedRectangle(cornerRadius: 22))
            Text("Відкрийте книжку").font(.title.bold())
            Text("TXT або PDF, українською чи російською. Скановані PDF розпізнаються на пристрої.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            Button { importing = true } label: { Label("Відкрити файл…", systemImage: "folder") }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }
}

struct LoadingOverlay: View {
    @EnvironmentObject private var model: ReaderModel

    var body: some View {
        VStack(spacing: 14) {
            if let progress = model.ocrProgress {
                Text("Розпізнавання тексту: сторінка \(progress.done) з \(progress.total)")
                ProgressView(value: Double(progress.done), total: Double(max(progress.total, 1))).frame(width: 280)
                Button("Скасувати", role: .cancel) { model.cancelLoading() }
            } else {
                ProgressView()
                Text(model.status)
            }
        }
        .padding(28)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
    }
}

/// Asks for the language of a scanned PDF before recognizing it.
struct OCRSheet: View {
    @EnvironmentObject private var model: ReaderModel
    @Environment(\.dismiss) private var dismiss
    let prompt: ReaderModel.OCRPrompt
    @State private var language = "uk"

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top, spacing: 16) {
                Image("Logo").resizable().frame(width: 64, height: 64).clipShape(RoundedRectangle(cornerRadius: 14))
                VStack(alignment: .leading, spacing: 8) {
                    Text(prompt.recognizedLanguage == nil ? "Розпізнати текст у скані?" : "Розпізнати текст заново?")
                        .font(.title2.bold())
                    Text(prompt.recognizedLanguage == nil
                         ? "Цей PDF — скан без текстового шару (\(prompt.pages) стор.)."
                         : "Документ уже розпізнано. Якщо мову вибрано неправильно, виберіть правильну.")
                }
            }
            Picker("Мова тексту", selection: $language) {
                Text("Українська").tag("uk")
                Text("Русский").tag("ru")
            }
            .pickerStyle(.segmented)
            Text("Розпізнавання виконується на пристрої вбудованим рушієм Apple Vision. Результат зберігається, тож повторне відкриття миттєве.")
                .font(.footnote)
                .foregroundStyle(.secondary)
            HStack {
                Button("Скасувати", role: .cancel) { dismiss() }
                Spacer()
                Button("Розпізнати") {
                    dismiss()
                    model.open(prompt.url, ocrLanguage: language)
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .presentationDetents([.height(340)])
        .onAppear {
            language = prompt.recognizedLanguage ?? (model.language == "ru" ? "ru" : "uk")
        }
    }
}
