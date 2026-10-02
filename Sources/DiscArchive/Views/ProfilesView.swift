import SwiftUI

struct ProfilesView: View {
    let store: ArchiveStore
    @SceneStorage("profiles.selection") private var selection: String?
    @State private var search = ""
    private var presets: [JSONValue] { store.presets.filter { search.isEmpty || $0["name"].string.localizedCaseInsensitiveContains(search) } }
    private var profiles: [JSONValue] { store.profiles.filter { search.isEmpty || $0["collection"].string.localizedCaseInsensitiveContains(search) } }

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                List(selection: $selection) {
                    Section("Encoding presets") {
                        ForEach(presets, id: \.stableID) { value in
                            Label(value["name"].string, systemImage: value["builtin"].bool ? "lock" : "slider.horizontal.3")
                                .lineLimit(1).tag("preset:" + value["id"].string)
                        }
                    }
                    Section("Saved discs") {
                        ForEach(profiles, id: \.stableID) { value in
                            Label(value["collection"].string, systemImage: "opticaldisc")
                                .lineLimit(1).tag("disc:" + value["disc_id"].string)
                        }
                        if profiles.isEmpty { Text(search.isEmpty ? "No saved discs" : "No matching discs").font(.caption).foregroundStyle(.secondary).selectionDisabled() }
                    }
                }.listStyle(.sidebar)
                Divider()
                Text("\(store.presets.count) presets · \(store.profiles.count) saved \(store.profiles.count == 1 ? "disc" : "discs")")
                    .font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(12)
            }.frame(minWidth: 200, idealWidth: 230, maxWidth: 280, maxHeight: .infinity)
            Group {
                if let preset = store.presets.first(where: { "preset:" + $0["id"].string == selection }) {
                    PresetDetailView(store: store, preset: preset) { selection = "preset:" + $0 }.id(preset["id"].string)
                } else if let profile = store.profiles.first(where: { "disc:" + $0["disc_id"].string == selection }) {
                    DiscProfileDetailView(store: store, profile: profile).id(profile["disc_id"].string)
                } else {
                    ContentUnavailableView("Choose a profile", systemImage: "slider.horizontal.3", description: Text("Select an encoding preset or a saved disc in the list."))
                }
            }.frame(minWidth: 390, maxWidth: .infinity, maxHeight: .infinity)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
        .searchable(text: $search, prompt: "Search profiles")
        .onAppear { selectFirstIfNeeded() }
        .onChange(of: store.presets.map(\.stableID) + store.profiles.map(\.stableID)) { _, _ in selectFirstIfNeeded() }
    }
    private func selectFirstIfNeeded() {
        let ids = store.presets.map { "preset:" + $0["id"].string } + store.profiles.map { "disc:" + $0["disc_id"].string }
        if selection == nil || !ids.contains(selection ?? "") { selection = ids.first }
    }
}

struct PresetDetailView: View {
    let store: ArchiveStore
    let preset: JSONValue
    let selectPreset: (String) -> Void
    @State private var draft = ArchiveSettings()
    @State private var name = ""
    @State private var duplicateName = ""
    @State private var category = "video"
    @State private var confirmDelete = false
    @State private var showDuplicate = false
    @State private var loadedRevision: JSONValue = .null
    private var builtin: Bool { preset["builtin"].bool }
    private var categories: [RecipeCategory] { RecipeCategory.all.filter { ["video", "audio", "subtitles", "destination", "retention"].contains($0.id) } }
    private var fields: [String] { (categories.first { $0.id == category }?.fields ?? []).filter { preset["settings"].object[$0] != nil } }
    private var dirty: Bool { name != preset["name"].string || draft.values != preset["settings"].object }

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(preset["name"].string).font(.title2.weight(.semibold))
                    Label(builtin ? "Built-in preset" : "Custom preset", systemImage: builtin ? "lock" : "slider.horizontal.3")
                        .font(.callout).foregroundStyle(.secondary)
                    Text(summary).font(.callout).foregroundStyle(.secondary)
                }
                Spacer(minLength: 12)
                Button { duplicateName = name + " copy"; showDuplicate = true } label: { Label("Duplicate…", systemImage: "plus.square.on.square") }
                    .disabled(store.busy || !store.connected).help("Create an editable copy of this preset")
            }.padding(20)
            Picker("Recipe section", selection: $category) {
                ForEach(categories) { Text($0.id == "destination" ? "Storage" : $0.id == "retention" ? "Retention" : $0.title).tag($0.id) }
            }.pickerStyle(.segmented).labelsHidden().padding(.horizontal, 20).padding(.bottom, 16)
            Divider()
            Form {
                if !builtin { Section("Preset") { TextField("Name", text: $name) } }
                if loadedRevision != preset["revision"] {
                    Section {
                        Label("Changed elsewhere. Reload before saving.", systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                        Button("Reload preset") { load(preset) }
                    }
                }
                Section(categories.first { $0.id == category }?.title ?? "Recipe") {
                    if builtin {
                        ForEach(fields, id: \.self) { key in
                            LabeledContent(fieldLabel(key)) {
                                Text(displayValue(preset["settings"][key])).foregroundStyle(.secondary).textSelection(.enabled)
                            }.accessibilityElement(children: .combine)
                        }
                    } else { RecipeEditor(draft: $draft, schema: store.schema, fields: fields) }
                }
            }.formStyle(.grouped).frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider()
            HStack {
                if builtin { Text("Duplicate this preset to change its settings.").font(.caption).foregroundStyle(.secondary) }
                else {
                    Button("Delete…", role: .destructive) { confirmDelete = true }
                    Spacer()
                    Button("Revert") { load(preset) }.disabled(!dirty)
                    Button("Save changes") {
                        Task {
                            await store.mutate("PATCH", "/presets/\(preset["id"].string)", ["expected_revision": loadedRevision, "name": .string(name), "settings": .object(draft.values)])
                            if store.error == nil, let fresh = store.presets.first(where: { $0["id"] == preset["id"] }) { load(fresh) }
                        }
                    }.buttonStyle(.borderedProminent).disabled(!dirty || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || loadedRevision != preset["revision"])
                }
                if builtin { Spacer() }
            }.padding(16).disabled(store.busy || !store.connected)
        }.frame(maxWidth: .infinity, maxHeight: .infinity).onAppear { load(preset) }
        .sheet(isPresented: $showDuplicate) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Duplicate preset").font(.headline)
                Text("Create an editable copy of \(preset["name"].string).").foregroundStyle(.secondary)
                TextField("Preset name", text: $duplicateName).textFieldStyle(.roundedBorder)
                HStack {
                    Spacer()
                    Button("Cancel") { showDuplicate = false }.keyboardShortcut(.cancelAction)
                    Button("Create preset") {
                        Task {
                            await store.mutate("POST", "/presets", ["name": .string(duplicateName.trimmingCharacters(in: .whitespacesAndNewlines)), "base_id": preset["id"]])
                            if store.error == nil {
                                showDuplicate = false
                                if let created = store.presets.last(where: { !$0["builtin"].bool && $0["name"].string == duplicateName.trimmingCharacters(in: .whitespacesAndNewlines) }) { selectPreset(created["id"].string) }
                            }
                        }
                    }.keyboardShortcut(.defaultAction).disabled(duplicateName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.busy)
                }
            }.padding(24).frame(width: 380)
        }
        .confirmationDialog("Delete this custom preset?", isPresented: $confirmDelete) {
            Button("Delete preset", role: .destructive) { Task { await store.mutate("DELETE", "/presets/\(preset["id"].string)", ["expected_revision": loadedRevision]) } }
        } message: { Text("Existing job recipes remain unchanged.") }
    }
    private func load(_ value: JSONValue) {
        loadedRevision = value["revision"]; draft = ArchiveSettings(values: value["settings"].object); name = value["name"].string; duplicateName = name + " copy"
    }
    private var summary: String {
        switch preset["id"].string {
        case "balanced": "HEVC with a balance of quality and file size."
        case "compatibility": "H.264 for broad playback compatibility."
        case "original": "Verified originals with no lossy video encoding."
        case "legacy": "Your previous encoding and language preferences."
        default: preset["settings"]["mode"].string == "original" ? "Verified originals with no lossy video encoding." : "A reusable recipe for new archives."
        }
    }
    private func displayValue(_ value: JSONValue) -> String {
        if case .bool(let flag) = value { return flag ? "On" : "Off" }
        if case .array(let values) = value { return values.isEmpty ? "All languages" : values.map(\.display).joined(separator: ", ") }
        if value.string.isEmpty && value.number == nil { return "Automatic" }
        return choiceLabel(value.display)
    }
}

struct DiscProfileDetailView: View {
    let store: ArchiveStore
    let profile: JSONValue
    @State private var collection = ""
    @State private var kind = "film"
    @State private var titles: [ArchiveTitle] = []
    @State private var overrides = ArchiveSettings()
    @State private var category = "video"
    @State private var confirmDelete = false
    @State private var loadedRevision: JSONValue = .null
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 6) {
                    Text(profile["collection"].string).font(.title2.weight(.semibold))
                    Label("Saved disc mapping", systemImage: "opticaldisc").font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
            }.padding(20)
            Divider()
            Form {
            Section("Confirmed disc mapping") {
                TextField("Collection", text: $collection)
                if loadedRevision != profile["revision"] {
                    Text("This mapping changed elsewhere. Reload before saving.").font(.caption).foregroundStyle(.orange)
                    Button("Reload mapping") {
                        load(profile)
                    }
                }
                Picker("Kind", selection: $kind) { Text("Film").tag("film"); Text("Series").tag("series"); Text("Extras").tag("extras") }
                ForEach($titles) { $title in TextField("Title \(title.id)", text: $title.name) }
                Text(profile["disc_id"].string).font(.caption.monospaced()).textSelection(.enabled)
            }
            Section("Disc recipe overrides") {
                Picker("Section", selection: $category) {
                    ForEach(RecipeCategory.all.filter { ["video", "audio", "subtitles", "retention"].contains($0.id) }) { Text($0.id == "retention" ? "Retention" : $0.title).tag($0.id) }
                }.pickerStyle(.segmented)
                RecipeEditor(draft: $overrides, schema: store.schema, fields: RecipeCategory.all.first { $0.id == category }?.fields, fallback: store.status?.settings ?? ArchiveSettings())
                Text("Only controls you change become disc-specific overrides. Existing jobs keep their snapshots.").font(.caption).foregroundStyle(.secondary)
            }
            }.formStyle(.grouped).frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider()
                HStack {
                    Button("Forget disc…", role: .destructive) { confirmDelete = true }
                    Spacer()
                    Button("Save mapping") { Task {
                        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
                        let encoded = try? encoder.encode(titles)
                        let value = encoded.flatMap { try? JSONDecoder().decode(JSONValue.self, from: $0) } ?? .array([])
                        await store.mutate("PATCH", "/profiles/\(profile["disc_id"].string)", ["expected_revision": loadedRevision, "collection": .string(collection), "kind": .string(kind), "titles": value, "overrides": .object(overrides.values)])
                        if store.error == nil, let fresh = store.profiles.first(where: { $0["disc_id"] == profile["disc_id"] }) { load(fresh) }
                    } }.buttonStyle(.borderedProminent).disabled(loadedRevision != profile["revision"])
                }.padding(16).disabled(store.busy || !store.connected)
        }.frame(maxWidth: .infinity, maxHeight: .infinity).onAppear { load(profile) }.confirmationDialog("Forget this disc mapping?", isPresented: $confirmDelete) {
            Button("Forget mapping", role: .destructive) { Task { await store.mutate("DELETE", "/profiles/\(profile["disc_id"].string)", ["expected_revision": loadedRevision]) } }
        } message: { Text("Files and existing jobs remain. This disc will need confirmation before automatic processing.") }
    }
    private func load(_ value: JSONValue) {
        loadedRevision = value["revision"]; collection = value["collection"].string; kind = value["kind"].string
        overrides = ArchiveSettings(values: value["overrides"].object); titles = decodeTitles(value["titles"])
    }

}
