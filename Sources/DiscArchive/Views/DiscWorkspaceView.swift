import SwiftUI
import AppKit

struct DiscWorkspaceView: View {
    let store: ArchiveStore
    @Binding var localSource: String?
    let didStart: (String) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Your discs, safely archived.").font(.largeTitle.bold())
                        Text("Insert a disc. Disc Porter remembers its identity, folders and checkpoints.")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                if store.status?.settings.outputRoot.isEmpty != false {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 12) {
                            Label("Choose an archive folder to get started", systemImage: "folder.badge.plus").font(.headline)
                            Text("Use a folder on your SSD. Originals and MP4s stay together; the job history also stays on your Mac.")
                                .foregroundStyle(.secondary)
                            Button("Choose archive folder…") {
                                if let path = FilePanels.folder() {
                                    var settings = store.status?.settings ?? ArchiveSettings()
                                    settings.outputRoot = path
                                    Task { await store.settings(settings) }
                                }
                            }.buttonStyle(.borderedProminent).disabled(!store.connected)
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
                    }
                }
                if store.discs.isEmpty && localSource == nil {
                    ContentUnavailableView {
                        Label(store.scanning ? "Reading disc information" : "Ready for your next disc", systemImage: "opticaldisc")
                    } description: {
                        Text("Connect your DVD or Blu-ray drive, insert a disc and choose Scan. Saved disc profiles can start automatically when enabled in Settings.")
                    } actions: {
                        Button("Scan for discs") { Task { await store.scan() } }.disabled(store.scanning || !store.connected)
                    }.frame(minHeight: 200)
                }
                ForEach(store.discs) { disc in
                    DiscIdentificationView(store: store, disc: disc, localSource: nil, didStart: didStart)
                        .id(disc.id)
                }
                if let localSource {
                    DiscIdentificationView(store: store, disc: nil, localSource: localSource, didStart: didStart)
                        .id(localSource)
                }
                Divider()
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Already have an original video?").font(.headline)
                        Text("Archive a local MKV or other video through the same checkpoint workflow.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Choose video…") { localSource = FilePanels.media() }.disabled(!store.connected)
                }
                if let tools = store.status?.tools {
                    HStack(spacing: 20) {
                        ForEach(["makemkv", "ffmpeg", "ffprobe"], id: \.self) { name in
                            Label(name == "makemkv" ? "MakeMKV" : name.uppercased(), systemImage: tools[name] ?? nil != nil ? "checkmark.circle" : "exclamationmark.circle")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }.padding(28).frame(maxWidth: 900, alignment: .leading).frame(maxWidth: .infinity)
        }
        .navigationTitle("Discs")
    }
}

private struct TitleSelection: Identifiable {
    let id: Int
    var selected: Bool
    var name: String
    let detail: String
}

struct DiscIdentificationView: View {
    let store: ArchiveStore
    let disc: ArchiveDisc?
    let localSource: String?
    let didStart: (String) -> Void
    @State private var collection = ""
    @State private var kind = "film"
    @State private var titles: [TitleSelection] = []
    @State private var stopAfter = Checkpoint.complete
    @State private var remember = true
    @State private var namesConfirmed = false

    var ready: Bool {
        !collection.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        titles.contains(where: \.selected) &&
        titles.filter(\.selected).allSatisfy { !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } &&
        namesConfirmed && store.status?.settings.outputRoot.isEmpty == false && !store.busy
    }

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top, spacing: 14) {
                    Image(systemName: disc == nil ? "film" : "opticaldisc").font(.system(size: 32)).foregroundStyle(.tint).accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(disc?.label ?? URL(fileURLWithPath: localSource ?? "").lastPathComponent).font(.title2.bold())
                        Text(disc == nil ? "Local video source" : "\(disc!.format) · \(disc!.identified ? "Saved disc profile" : "First-time identification")")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                if let disc, !disc.message.isEmpty {
                    Text(disc.message).font(.callout).foregroundStyle(.secondary)
                }
                Text("Confirm unfamiliar discs once. Saved profiles match the disc fingerprint and reuse these folders and names.")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    TextField("Collection name", text: $collection).textFieldStyle(.roundedBorder)
                        .accessibilityLabel("Collection folder name")
                    Picker("Content", selection: $kind) {
                        Text("Film").tag("film")
                        Text("Series").tag("series")
                        Text("Extras").tag("extras")
                    }.frame(width: 170)
                }
                if titles.isEmpty {
                    Label("No title information available. Scan again after the drive is ready.", systemImage: "info.circle")
                        .foregroundStyle(.secondary)
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Titles to archive").font(.headline)
                        Text(kind == "series" ? "Use the verified episode name, for example S01E01_Episode_Title. Disc order alone may differ from episode order." : "Select the intended cut and give each file a clear name.")
                            .font(.caption).foregroundStyle(.secondary)
                        ForEach($titles) { $title in
                            HStack(spacing: 12) {
                                Toggle("Title \(title.id)", isOn: $title.selected).frame(width: 100, alignment: .leading)
                                TextField("File name", text: $title.name).textFieldStyle(.roundedBorder)
                                    .accessibilityLabel("File name for title \(title.id)")
                                Text(title.detail).font(.caption).foregroundStyle(.secondary).frame(width: 120, alignment: .trailing)
                            }
                        }
                    }
                }
                Toggle("I checked the title selection and file names", isOn: $namesConfirmed)
                if disc != nil { Toggle("Remember this disc for future automatic starts", isOn: $remember) }
                Divider()
                HStack {
                    Picker("Work until", selection: $stopAfter) {
                        ForEach(Checkpoint.allCases) { checkpoint in Text(checkpoint.title).tag(checkpoint) }
                    }.frame(maxWidth: 370)
                    Spacer()
                    Button("Start archive") { start() }.buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(!ready).keyboardShortcut(.defaultAction)
                }
                Text(stopAfter.explanation).font(.caption).foregroundStyle(.secondary)
            }.padding(14)
        }
        .onAppear { seed() }
    }

    private func seed() {
        collection = disc?.collection ?? (disc?.label ?? URL(fileURLWithPath: localSource ?? "").deletingPathExtension().lastPathComponent)
        kind = disc?.kind ?? "film"
        if let disc {
            titles = disc.titles.map { TitleSelection(id: $0.id, selected: $0.selected ?? false, name: $0.name,
                detail: [$0.duration, $0.size].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")) }
            namesConfirmed = disc.identified
        } else {
            titles = [TitleSelection(id: 0, selected: true, name: collection, detail: "Local source")]
        }
    }
    private func start() {
        let selected = titles.filter(\.selected).map { ArchiveTitle(id: $0.id, name: $0.name) }
        let request = JobRequest(sourcePath: disc?.sourcePath ?? localSource ?? "", discId: disc?.id,
            collection: collection, kind: kind, titles: selected, stopAfter: stopAfter.rawValue)
        Task {
            if let id = await store.start(request, saveProfile: remember && disc != nil) { didStart(id) }
        }
    }
}
