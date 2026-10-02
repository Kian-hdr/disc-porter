import AppKit

@MainActor enum FilePanels {
    static func folder(title: String = "Choose archive folder") async -> String? {
        let panel = NSOpenPanel(); panel.title = title; panel.prompt = "Choose"
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        return await present(panel)
    }
    static func media() async -> String? {
        let panel = NSOpenPanel(); panel.title = "Choose video source"; panel.prompt = "Use source"
        panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        return await present(panel)
    }
    private static func present(_ panel: NSOpenPanel) async -> String? {
        await withCheckedContinuation { continuation in
            if let window = NSApp.keyWindow {
                panel.beginSheetModal(for: window) { result in continuation.resume(returning: result == .OK ? panel.url?.path : nil) }
            } else {
                panel.begin { result in continuation.resume(returning: result == .OK ? panel.url?.path : nil) }
            }
        }
    }
}
