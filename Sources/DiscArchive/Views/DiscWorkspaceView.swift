import SwiftUI

struct DiscWorkspaceView: View {
    let store: ArchiveStore
    @Binding var localSource: String?
    let didStart: (String) -> Void
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("Sources").font(.title2.weight(.semibold)); Spacer()
                    Button("Choose video…") { Task { localSource = await FilePanels.media() } }.disabled(!store.connected)
                }
                if store.status?.settings.outputRoot.isEmpty != false {
                    HStack { Label("Choose an archive folder in Settings before starting.", systemImage: "folder.badge.plus"); Spacer(); Button("Open Settings") { store.destination = .settings } }
                        .padding().background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                }
                if store.discs.isEmpty && localSource == nil {
                    ContentUnavailableView(store.scanning ? "Reading discs" : "Ready for a source", systemImage: "opticaldisc", description: Text("Insert a disc and Scan, or choose a local video. Unknown discs require confirmed title mappings."))
                }
                ForEach(store.discs, id: \.sourcePath) { disc in DiscComposerView(store: store, disc: disc, localSource: nil, didStart: didStart).id(disc.id + disc.sourcePath) }
                if let localSource { DiscComposerView(store: store, disc: nil, localSource: localSource, didStart: didStart).id(localSource) }
            }.padding(20)
        }
    }
}

struct DiscComposerView: View {
    let store: ArchiveStore
    let disc: ArchiveDisc?
    let localSource: String?
    let didStart: (String) -> Void
    @State private var collection = ""
    @State private var kind = "film"
    @State private var titles: [TitleDraft] = []
    @State private var confirmed = false
    @State private var remember = true
    @State private var stopAfter = "complete"
    @State private var presetID = "balanced"
    @State private var overrides = ArchiveSettings()
    @State private var customize = false
    @State private var preview: JSONValue = .null
    @State private var previewFingerprint = ""
    @State private var previewSettingsRevision = 0
    @State private var suggestions: [JSONValue] = []
    @State private var query = ""
    @State private var previewing = false
    @State private var confirmTransforms = false
    @State private var startAttempt = StartAttempt()
    private var sourcePath: String { disc?.sourcePath ?? localSource ?? "" }
    private var fingerprint: String {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        return String(decoding: (try? encoder.encode(request)) ?? Data(), as: UTF8.self)
    }
    private var request: JobRequest {
        var request = JobRequest(sourcePath: sourcePath, discId: disc?.id, collection: collection, kind: kind, titles: titles.filter(\.selected).map(\.title), stopAfter: stopAfter)
        request.presetId = presetID
        request.overrides = customize ? overrides : nil
        request.rememberProfile = disc != nil && remember
        request.expectedSettingsRevision = store.status?.settings.revision
        request.confirmTransforms = confirmTransforms
        return request
    }
    private var ready: Bool { confirmed && !collection.trimmingCharacters(in: .whitespaces).isEmpty && titles.contains(where: \.selected) && titles.filter(\.selected).allSatisfy { !$0.name.trimmingCharacters(in: .whitespaces).isEmpty && $0.metadataValid } }
    private var previewCurrent: Bool { previewFingerprint == fingerprint && previewSettingsRevision == store.status?.settings.revision }
    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Label(disc?.label ?? URL(fileURLWithPath: sourcePath).lastPathComponent, systemImage: disc == nil ? "film" : "opticaldisc").font(.headline)
                    Spacer(); Text(disc?.format ?? "Local source").foregroundStyle(.secondary)
                }
                if let message = disc?.message { Text(message).font(.caption).foregroundStyle(.secondary) }
                HStack {
                    TextField("Collection", text: $collection)
                    Picker("Kind", selection: $kind) { Text("Film").tag("film"); Text("Series").tag("series"); Text("Extras").tag("extras") }.frame(width: 185)
                }
                ForEach($titles) { $title in TitleSelectionView(title: $title, kind: kind, schema: store.schema, fallback: ArchiveSettings(values: store.presets.first { $0["id"].string == presetID }?["settings"].object ?? [:])) }
                if titles.isEmpty { Text("Title information is unavailable. Scan again before starting.").foregroundStyle(.secondary) }
                DisclosureGroup("Identify this source") {
                    HStack {
                        TextField("Search title", text: $query)
                        Button("Local suggestions") { identify("local") }
                        Button("Online suggestions") { identify("tmdb") }.disabled(store.status?.settings["online_lookup"].bool != true)
                    }
                    ForEach(suggestions, id: \.stableID) { suggestion in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(suggestion["title"].string)
                                Text("\(suggestion["provider"].display) · \(suggestion["evidence"].display)").font(.caption).foregroundStyle(.secondary)
                            }
                            if let url = URL(string: suggestion["evidence"].string), ["https", "http"].contains(url.scheme ?? "") { Link("Source", destination: url) }
                            Spacer(); Button("Use suggestion") {
                                collection = suggestion["title"].string
                                if ["film", "series", "extras"].contains(suggestion["kind"].string) { kind = suggestion["kind"].string }
                                if titles.count == 1 { titles[0].name = collection; if let year = suggestion["year"].number { titles[0].year = String(Int(year)) } }
                                confirmed = false
                            }
                        }
                    }
                    Text("Suggestions do not establish episode order, cut or content identity. Confirm the mapping below.").font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Picker("Preset", selection: $presetID) {
                        ForEach(store.presets, id: \.stableID) { Text($0["name"].string).tag($0["id"].string) }
                    }
                    Picker("Stop after", selection: $stopAfter) { ForEach(Checkpoint.allCases) { Text($0.title).tag($0.rawValue) } }
                }
                Toggle("Manual recipe overrides", isOn: $customize)
                if customize {
                    DisclosureGroup("Video, audio, subtitles and retention") {
                        Form { RecipeEditor(draft: $overrides, schema: store.schema, fields: RecipeCategory.all.filter { ["video", "audio", "subtitles", "retention"].contains($0.id) }.flatMap(\.fields), fallback: ArchiveSettings(values: store.presets.first { $0["id"].string == presetID }?["settings"].object ?? [:])) }
                            .formStyle(.grouped).frame(minHeight: 340)
                    }
                }
                Toggle("I checked the selected titles, cuts and file names", isOn: $confirmed)
                if disc != nil { Toggle("Remember this confirmed disc mapping", isOn: $remember) }
                if let localSource { DisclosureGroup("Source preview") { MediaPreviewView(path: localSource) } }
                if preview != .null {
                    GroupBox("Archive preview") {
                        VStack(alignment: .leading, spacing: 8) {
                            LabeledContent("Mode", value: choiceLabel(preview["effective_settings"]["mode"].string))
                            LabeledContent("Video", value: preview["effective_settings"]["video_codec"].string.uppercased())
                            LabeledContent("Container", value: preview["effective_settings"]["output_container"].string.uppercased())
                            StructuredValueView(value: preview["destinations"])
                            if !preview["transforms"].array.isEmpty { StructuredValueView(value: preview["transforms"]) }
                            if !preview["reason"].string.isEmpty { Text(preview["reason"].string).foregroundStyle(.orange) }
                            DisclosureGroup("Advanced effective recipe") { StructuredValueView(value: preview["title_settings"]) }
                        }.padding(8)
                    }
                    if preview["requires_confirmation"].bool {
                        Toggle("Approve the listed source transformations", isOn: $confirmTransforms)
                    }
                    if !previewCurrent { Text("The plan changed. Refresh the preview before starting.").font(.caption).foregroundStyle(.orange) }
                }
                HStack {
                    Button(previewing ? "Checking…" : "Preview archive") { Task { await makePreview() } }.disabled(!ready || previewing || store.busy)
                    Spacer()
                    Button("Start archive") { Task {
                        let plan = preview["plan_fingerprint"].string
                        var accepted = request
                        accepted.expectedPlanFingerprint = plan
                        accepted.idempotencyKey = startAttempt.key(for: plan + ":" + fingerprint)
                        if let id = await store.start(accepted, saveProfile: disc != nil && remember) { startAttempt.completed(); didStart(id) }
                    } }
                        .buttonStyle(.borderedProminent).disabled(!ready || !previewCurrent || !preview["can_apply"].bool || store.busy || store.status?.disconnectFenced == true || preview["requires_confirmation"].bool && !confirmTransforms || preview["plan_fingerprint"].string.isEmpty)
                }
            }.padding(12).textFieldStyle(.roundedBorder)
        }.onAppear { seed() }.task {
            if store.presets.isEmpty { store.presets = await store.query("GET", "/presets")?["presets"].array ?? [] }
            if disc == nil { await loadLocalInventory() }
        }
    }
    private func seed() {
        collection = disc?.collection ?? disc?.label ?? URL(fileURLWithPath: sourcePath).deletingPathExtension().lastPathComponent
        query = collection; kind = disc?.kind ?? "film"; presetID = store.status?.settings["preset_id"].string ?? "balanced"
        stopAfter = store.status?.settings["default_checkpoint"].string ?? "complete"
        if let disc {
            titles = disc.titles.map { title in
                var draft = TitleDraft(id: title.id, selected: title.selected == true, name: title.name, duration: title.duration ?? "")
                if let mapped = disc.selectedTitles?.first(where: { $0.id == title.id }) {
                    draft.audioIDs = Set(mapped.audioStreams ?? []); draft.subtitleIDs = Set(mapped.subtitleStreams ?? [])
                    draft.manualAudio = mapped.audioStreams != nil; draft.manualSubtitles = mapped.subtitleStreams != nil
                    draft.season = mapped.season.map(String.init) ?? ""; draft.episode = mapped.episode.map(String.init) ?? ""; draft.year = mapped.year.map(String.init) ?? ""
                    draft.overrides = mapped.overrides
                    draft.defaultAudioID = mapped.defaultAudioStream; draft.defaultSubtitleID = mapped.defaultSubtitleStream
                    draft.overrideForced = mapped.forcedSubtitleStreams != nil; draft.forcedIDs = Set(mapped.forcedSubtitleStreams ?? [])
                }
                draft.streams = inventory(disc.streamInventory?[String(title.id)] ?? .null)
                return draft
            }; confirmed = disc.identified
        } else { titles = [.init(id: 0, selected: true, name: collection)] }
    }
    private func inventory(_ raw: JSONValue) -> [JSONValue] {
        if !raw.array.isEmpty { return raw.array }
        return raw.object.keys.sorted().map { key in var stream = raw[key]; stream["index"] = .number(Double(key) ?? 0); return stream }
    }
    private func loadLocalInventory() async {
        if let value = await store.query("POST", "/identify", ["provider": .string("local"), "source_path": .string(sourcePath), "query": .string(query)]) {
            suggestions = value["suggestions"].array
            let raw = value["technical_inventory"]
            let streams = raw.array.isEmpty ? raw["streams"].array : raw.array
            if !titles.isEmpty { titles[0].streams = streams }
        }
    }
    private func identify(_ provider: String) {
        Task {
            var body: [String: JSONValue] = ["provider": .string(provider), "query": .string(query)]
            if let disc { body["disc_id"] = .string(disc.id) }
            else if provider == "local" { body["source_path"] = .string(sourcePath) }
            suggestions = await store.query("POST", "/identify", body)?["suggestions"].array ?? []
        }
    }
    private func makePreview() async {
        previewing = true; defer { previewing = false }
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        guard let data = try? encoder.encode(request), let body = try? JSONDecoder().decode(JSONValue.self, from: data) else { return }
        let originalFingerprint = fingerprint; let originalRevision = store.status?.settings.revision ?? 0
        preview = await store.query("POST", "/jobs/preview", body.object) ?? .null
        previewFingerprint = originalFingerprint; previewSettingsRevision = originalRevision
    }
}
