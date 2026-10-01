import SwiftUI
import AppKit

struct ConnectionView: View {
    @State private var copied = false
    private var root: String {
        Bundle.main.object(forInfoDictionaryKey: "DiscPorterSourceRoot") as? String ?? "<repository-folder>"
    }
    private var launcher: String { root + "/mcp/run.sh" }
    private var config: String {
        "[mcp_servers.disc_porter]\ncommand = \"\(launcher.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\""))\""
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Image(systemName: "point.3.connected.trianglepath.dotted").font(.system(size: 42)).foregroundStyle(.tint)
                    .accessibilityHidden(true)
                Text("A small connection. A complete workflow.").font(.largeTitle.bold())
                Text("An AI assistant can start an archive, inspect a report or request a checkpoint. Disc Porter handles the long-running work locally, even after the chat closes.")
                    .foregroundStyle(.secondary)
                GroupBox {
                    VStack(alignment: .leading, spacing: 16) {
                        Label("Local MCP connection", systemImage: "lock.shield").font(.headline)
                        Text("Run the repository's MCP setup once, then add this server to your client. Reopen the client to discover the tools. Keep Disc Porter open for the first connection.")
                        Text(config).font(.system(.body, design: .monospaced)).textSelection(.enabled)
                            .padding(12).frame(maxWidth: .infinity, alignment: .leading).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                        HStack {
                            Button(copied ? "Copied" : "Copy Codex configuration") {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(config, forType: .string)
                                copied = true
                            }
                            Button("Open MCP instructions") {
                                NSWorkspace.shared.open(URL(fileURLWithPath: root + "/mcp/README.md"))
                            }
                        }
                    }.padding(14)
                }
                Label("Status and reports stay compact", systemImage: "text.alignleft")
                Label("Ripping and encoding require no AI model", systemImage: "desktopcomputer")
                Label("Connection credentials stay on your Mac", systemImage: "key.horizontal")
                Text("Using an AI client may consume that client's tokens. The processing engine has no model API dependency. MCP discovery requires one-time client configuration; the app cannot silently connect every AI service.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(32).frame(maxWidth: 850, alignment: .leading).frame(maxWidth: .infinity)
        }.navigationTitle("AI connection")
    }
}
