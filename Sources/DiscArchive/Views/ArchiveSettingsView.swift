import SwiftUI

struct ArchiveSettingsView: View {
    let store: ArchiveStore
    @State private var draft = ArchiveSettings()
    @State private var base = ArchiveSettings()
    @State private var category = "destination"
    @State private var search = ""
    @State private var loaded = false
    @State private var saved = false
    var body: some View {
        HSplitView {
            List(selection: $category) {
                ForEach(RecipeCategory.all) { Text($0.title).tag($0.id) }
                Text("AI & metadata").tag("connection")
                Text("Diagnostics").tag("diagnostics")
            }.frame(minWidth: 170, idealWidth: 200, maxWidth: 240)
            VStack(spacing: 0) {
                if category == "connection" { ConnectionView(store: store) }
                else if category == "diagnostics" { DiagnosticsView(store: store) }
                else {
                    Form {
                        if category == "video" {
                            Picker("Default preset", selection: Binding(get: { draft["preset_id"].string }, set: { draft["preset_id"] = .string($0) })) {
                                ForEach(store.presets, id: \.stableID) { preset in Text(preset["name"].string).tag(preset["id"].string) }
                            }
                            Text("Use Profiles to inspect and duplicate presets. Manual values override the chosen recipe.").font(.caption).foregroundStyle(.secondary)
                        }
                        if category == "automation" {
                            Section("macOS notifications") {
                                LabeledContent("System permission", value: store.notificationAuthorization)
                                HStack {
                                    Button("Allow notifications…") { Task { await store.authorizeNotifications() } }
                                    Button("Check permission") { Task { await store.refreshNotificationAuthorization() } }
                                }
                                Text("Notifications arrive while Disc Porter is running, including with its window closed. Work after Quit appears on next launch. Only Allow notifications requests macOS permission.").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if category == "tools" { Section("Installed tools") { StructuredValueView(value: store.capabilities["tools"]) } }
                        Section(RecipeCategory.all.first { $0.id == category }?.title ?? "Settings") {
                            RecipeEditor(draft: $draft, schema: store.schema, fields: search.isEmpty ? RecipeCategory.all.first { $0.id == category }?.fields : nil, search: search)
                        }
                    }.formStyle(.grouped)
                    Divider()
                    HStack {
                        Text(saved ? "Settings saved" : base.revision != store.status?.settings.revision ? "Settings changed elsewhere. Reload before saving." : "Changes affect new jobs.")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button("Reload") { load() }
                        Button("Save changes") {
                            Task { await store.settings(draft, original: base); if store.error == nil { load(); saved = true } }
                        }.buttonStyle(.borderedProminent).disabled(store.busy || !store.connected || draft.changes(from: base).isEmpty || base.revision != store.status?.settings.revision)
                    }.padding()
                }
            }.frame(minWidth: 450, maxWidth: .infinity, maxHeight: .infinity)
        }
        .searchable(text: $search, prompt: "Search settings")
        .onAppear { if !loaded { load() } }
        .onChange(of: store.status?.settings) { _, _ in if !loaded { load() } }
    }
    private func load() { if let value = store.status?.settings { base = value; draft = value; loaded = true; saved = false } }
}

struct DiagnosticsView: View {
    let store: ArchiveStore
    @State private var audit: JSONValue = .null
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Processing capabilities").font(.title2)
                StructuredValueView(value: store.capabilities)
                Divider()
                HStack { Text("Recent operations").font(.headline); Spacer(); Button("Refresh audit") { Task { audit = await store.query("GET", "/events?after=0&limit=30") ?? .null } } }
                StructuredValueView(value: audit)
            }.padding(20)
        }
    }
}
