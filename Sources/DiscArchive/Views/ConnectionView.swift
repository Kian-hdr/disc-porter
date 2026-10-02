import SwiftUI
import AppKit

struct ConnectionView: View {
    let store: ArchiveStore
    @State private var token = ""
    @State private var configured = false
    @State private var online = false
    @State private var copied = false
    private var helper: String { Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/DiscPorterHelper/disc-porter-helper").path }
    private var config: String {
        "[mcp_servers.disc_porter]\ncommand = \"\(helper.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\""))\"\nargs = [\"mcp\"]"
    }
    var body: some View {
        Form {
            Section("Local AI connection") {
                Text("The bundled MCP helper exposes the same archive operations as the app. Media processing runs locally without model calls.")
                Text(config).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                Button(copied ? "Copied" : "Copy Codex configuration") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(config, forType: .string); copied = true }
                Text("Configure your AI client once. Its model usage is separate from Disc Porter processing.").font(.caption).foregroundStyle(.secondary)
            }
            Section("Optional metadata suggestions") {
                Toggle("Enable online TMDb lookup", isOn: $online)
                    .onChange(of: online) { _, enabled in
                        guard enabled != store.status?.settings["online_lookup"].bool else { return }
                        Task { var draft = store.status?.settings ?? ArchiveSettings(); draft["online_lookup"] = .bool(enabled); await store.settings(draft) }
                    }
                Text("Local suggestions remain available offline. Online queries send search text only. Suggestions always require confirmation of title and cut.").font(.caption).foregroundStyle(.secondary)
                LabeledContent("TMDb credential", value: configured ? "Configured in Keychain" : "Not configured")
                SecureField("TMDb API token", text: $token)
                HStack {
                    Button("Save in Keychain") { Task { await store.mutate("POST", "/metadata/credential", ["token": .string(token)]); token = ""; await load() } }.disabled(token.isEmpty || store.busy)
                    Button("Remove credential", role: .destructive) { Task { await store.mutate("DELETE", "/metadata/credential"); await load() } }.disabled(!configured || store.busy)
                }
            }
        }.formStyle(.grouped).task { await load(); online = store.status?.settings["online_lookup"].bool ?? false }
    }
    private func load() async { configured = await store.query("GET", "/metadata/credential")?["configured"].bool ?? false }
}
