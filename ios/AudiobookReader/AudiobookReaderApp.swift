import SwiftUI

@main
struct AudiobookReaderApp: App {
    @StateObject private var model = ReaderModel()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        #if DEBUG
        SelfTest.runIfRequested()
        #endif
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onChange(of: scenePhase) { _, phase in
                    if phase != .active { model.savePosition() }
                }
        }
    }
}
