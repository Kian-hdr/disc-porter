import SwiftUI

struct TitleSelectionView: View {
    @Binding var title: TitleDraft
    let kind: String
    var schema: [String: JSONValue] = [:]
    var fallback = ArchiveSettings()
    @State private var category = "video"
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Toggle("Title \(title.id)", isOn: $title.selected).frame(width: 100, alignment: .leading)
                TextField("Verified file name", text: $title.name)
                Text(title.duration).font(.caption).foregroundStyle(.secondary)
            }
            if title.selected {
                DisclosureGroup("Streams & naming") {
                    HStack {
                        if kind == "series" { TextField("Season", text: $title.season); TextField("Episode", text: $title.episode) }
                        TextField("Year (optional)", text: $title.year)
                    }.frame(maxWidth: 460)
                    if !title.metadataValid { Text("Use whole numbers for season, episode and year, or leave them empty.").font(.caption).foregroundStyle(.orange) }
                    Toggle("Choose audio streams manually", isOn: $title.manualAudio)
                    Toggle("Choose subtitle streams manually", isOn: $title.manualSubtitles)
                    DefaultStreamPicker(label: "Default audio", type: "audio", selected: $title.defaultAudioID, streams: title.streams)
                    DefaultStreamPicker(label: "Default subtitle", type: "subtitle", selected: $title.defaultSubtitleID, streams: title.streams)
                    Toggle("Override forced subtitle flags", isOn: $title.overrideForced)
                    if title.overrideForced { Text("Select tracks marked forced. No selections clears all forced flags.").font(.caption).foregroundStyle(.secondary) }
                    ForEach(title.streams, id: \.stableID) { stream in
                        StreamSelectionRow(stream: stream, title: $title)
                    }
                    if title.streams.isEmpty { Text("No detailed stream inventory reported yet. The recipe's automatic stream policy will apply.").font(.caption).foregroundStyle(.secondary) }
                }.font(.callout)
                if !schema.isEmpty {
                    DisclosureGroup("Title recipe overrides") {
                        Picker("Section", selection: $category) {
                            ForEach(RecipeCategory.all.filter { ["video", "audio", "subtitles", "retention"].contains($0.id) }) { Text($0.title).tag($0.id) }
                        }
                        Form {
                            RecipeEditor(draft: Binding(get: { title.overrides ?? ArchiveSettings() }, set: { title.overrides = $0 }), schema: schema, fields: RecipeCategory.all.first { $0.id == category }?.fields, fallback: fallback)
                        }.formStyle(.grouped).frame(minHeight: 280)
                        if title.overrides != nil { Button("Use inherited recipe") { title.overrides = nil } }
                    }
                }
            }
        }.padding(.vertical, 4)
    }
}
private struct StreamSelectionRow: View {
    let stream: JSONValue
    @Binding var title: TitleDraft
    private var index: Int { Int(stream["index"].number ?? 0) }
    private var type: String { stream["codec_type"].string.isEmpty ? (stream["type"].string.isEmpty ? stream["1"].string.lowercased() : stream["type"].string) : stream["codec_type"].string }
    private var isSubtitle: Bool { type.contains("subtitle") }
    private var isAudio: Bool { type.contains("audio") }
    private var label: String {
        let codec = stream["codec_name"].string.isEmpty ? (stream["codec"].string.isEmpty ? stream["6"].string : stream["codec"].string) : stream["codec_name"].string
        let language = stream["tags"]["language"].string.isEmpty ? (stream["language"].string.isEmpty ? stream["3"].string : stream["language"].string) : stream["tags"]["language"].string
        return "Stream \(index) · \(type.isEmpty ? "Source stream" : type) · \(codec) · \(language.isEmpty ? "und" : language)"
    }
    var body: some View {
        if isSubtitle && title.overrideForced {
            Toggle("Forced: " + label, isOn: Binding(get: { title.forcedIDs.contains(index) }, set: { if $0 { title.forcedIDs.insert(index) } else { title.forcedIDs.remove(index) } }))
        }
        if isAudio && title.manualAudio || isSubtitle && title.manualSubtitles {
            Toggle(label, isOn: Binding(get: { isAudio ? title.audioIDs.contains(index) : title.subtitleIDs.contains(index) }, set: { included in
                if isAudio { if included { title.audioIDs.insert(index) } else { title.audioIDs.remove(index) } }
                else { if included { title.subtitleIDs.insert(index) } else { title.subtitleIDs.remove(index) } }
            }))
        } else { Text(label).font(.caption).foregroundStyle(.secondary) }
    }
}

private struct DefaultStreamPicker: View {
    let label: String
    let type: String
    @Binding var selected: Int?
    let streams: [JSONValue]
    var body: some View {
        Picker(label, selection: Binding(get: { selected ?? -1 }, set: { selected = $0 < 0 ? nil : $0 })) {
            Text("Automatic").tag(-1)
            ForEach(streams.filter { value in
                let kind = value["codec_type"].string.isEmpty ? (value["type"].string.isEmpty ? value["1"].string.lowercased() : value["type"].string) : value["codec_type"].string
                return kind.contains(type)
            }, id: \.stableID) { value in
                let index = Int(value["index"].number ?? 0)
                Text("Stream \(index)").tag(index)
            }
        }
    }
}
