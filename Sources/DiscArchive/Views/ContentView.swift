import SwiftUI

struct ContentView: View {
    let store: ArchiveStore
    @State private var selection: String? = "discs"
    @State private var localSource: String?

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                Section("Workspace") {
                    Label("Discs", systemImage: "opticaldisc").tag("discs")
                    Label("AI connection", systemImage: "point.3.connected.trianglepath.dotted").tag("mcp")
                }
                Section("Archive jobs") {
                    if store.jobs.isEmpty {
                        Text("No jobs yet").foregroundStyle(.secondary)
                    }
                    ForEach(store.jobs) { job in
                        Label {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(job.collection).lineLimit(1)
                                Text(job.state.capitalized).font(.caption).foregroundStyle(.secondary)
                            }
                        } icon: { Image(systemName: job.state == "completed" ? "checkmark.circle" : "tray.and.arrow.down") }
                        .tag(job.id)
                    }
                }
            }
            .listStyle(.sidebar)
            .navigationTitle("Disc Porter")
            .navigationSplitViewColumnWidth(min: 210, ideal: 240)
        } detail: {
            VStack(spacing: 0) {
                DisconnectBanner(store: store)
                Divider()
                if selection == "mcp" {
                    ConnectionView()
                } else if let job = store.jobs.first(where: { $0.id == selection }) {
                    JobDetailView(store: store, job: job)
                } else {
                    DiscWorkspaceView(store: store, localSource: $localSource) { id in selection = id }
                }
            }
            .toolbar {
                ToolbarItemGroup {
                    Button { Task { await store.scan() } } label: { Label("Scan", systemImage: "arrow.clockwise") }
                        .disabled(store.scanning || !store.connected).help("Read disc information without starting a rip")
                    SettingsLink { Label("Settings", systemImage: "gearshape") }
                }
            }
        }
        .alert("Disc Porter", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) {
            Button("OK") { store.error = nil }
        } message: { Text(store.error ?? "") }
        .sheet(isPresented: Binding(get: { store.reportText != nil }, set: { if !$0 { store.reportText = nil } })) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Verification report").font(.title2.bold())
                ScrollView { Text(store.reportText ?? "").font(.system(.body, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                Button("Done") { store.reportText = nil }.keyboardShortcut(.defaultAction)
            }.padding(24).frame(width: 740, height: 560)
        }
    }
}

struct DisconnectBanner: View {
    let store: ArchiveStore
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: !store.connected ? "bolt.slash" : store.safe ? "checkmark.shield.fill" : "externaldrive.fill")
                .font(.title3).foregroundStyle(store.safe ? Color.green : Color.orange)
            VStack(alignment: .leading, spacing: 3) {
                Text(!store.connected ? "Connecting to the local engine" : store.safe ? "No archive writes in progress" : "Keep the archive drive connected")
                    .font(.headline)
                Text(store.safe ? "Eject the SSD in Finder before unplugging. Completed checkpoints are saved." : "Prepare to disconnect finishes active work at its next checkpoint and disables automatic starts.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if !store.connected {
                Button("Reconnect") { Task { await store.reconnect() } }.disabled(store.busy)
            } else {
                Button("Prepare to disconnect") { Task { await store.prepareToDisconnect() } }
                    .disabled(store.busy || (store.safe && store.status?.settings.autoStart != true))
            }
        }
        .padding(.horizontal, 24).padding(.vertical, 16)
        .background(.thinMaterial)
        .accessibilityElement(children: .contain)
    }
}
