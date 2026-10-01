import AppKit

@MainActor enum FilePanels {
    static func folder() -> String? {
        let panel = NSOpenPanel()
        panel.title = "Choose your archive folder"
        panel.prompt = "Choose folder"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        return panel.runModal() == .OK ? panel.url?.path : nil
    }
    static func media() -> String? {
        let panel = NSOpenPanel()
        panel.title = "Choose a local video source"
        panel.prompt = "Use source"
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        return panel.runModal() == .OK ? panel.url?.path : nil
    }
}
