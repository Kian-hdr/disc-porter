import SwiftUI
import AppKit

struct LibraryView: View {
    let store: ArchiveStore
    @State private var selected: String?
    @State private var search = ""
    var items: [JSONValue] { store.library.filter { search.isEmpty || $0["title"].string.localizedCaseInsensitiveContains(search) } }
    var body: some View {
        HSplitView {
            Table(items.map(LibraryRow.init), selection: $selected) {
                TableColumn("Title", value: \.title)
                TableColumn("Kind", value: \.kind).width(70)
                TableColumn("Size", value: \.size).width(90)
            }.frame(minWidth: 280)
            if let item = items.first(where: { $0["id"].string == selected }) {
                LibraryDetailView(store: store, item: item).id(item["id"].string).frame(minWidth: 320, idealWidth: 380, maxWidth: 480)
            }
        }.searchable(text: $search, prompt: "Search archive")
            .overlay { if items.isEmpty { ContentUnavailableView("Archive library", systemImage: "film.stack", description: Text("Completed and explicitly imported media appear here.")) } }
    }
}
private struct LibraryRow: Identifiable {
    let id: String; let title: String; let kind: String; let size: String
    init(_ value: JSONValue) {
        id = value["id"].string; title = value["title"].string; kind = value["kind"].string.capitalized
        size = ByteCountFormatter.string(fromByteCount: Int64(value["bytes"].number ?? 0), countStyle: .file)
    }
}
struct LibraryDetailView: View {
    let store: ArchiveStore
    let item: JSONValue
    @State private var cleanup: JSONValue = .null
    @State private var confirmCleanup = false
    @State private var cleanupRevision = 0
    @State private var playback = "pending"
    @State private var perceptual = "pending"
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(item["title"].string).font(.title2)
                Text(item["path"].string).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                HStack {
                    Button("Job details") { store.selectedJobID = item["job_id"].string; store.destination = .queue }
                    Button("Reveal") { NSWorkspace.shared.selectFile(item["path"].string, inFileViewerRootedAtPath: "") }
                    Button("Export…") { Task {
                        if let path = await FilePanels.folder(title: "Export verified deliverables") {
                            await store.mutate("POST", "/exports", ["job_id": item["job_id"], "destination": .string(path), "expected_revision": .number(Double(currentRevision))])
                        }
                    } }
                }
                DisclosureGroup("Media preview") { MediaPreviewView(path: item["path"].string) }
                GroupBox("Technical verification") { StructuredValueView(value: item["verification"]).padding(8) }
                GroupBox("Originals") { StructuredValueView(value: item["original_status"]).padding(8) }
                GroupBox("Playback review") {
                    VStack(spacing: 10) {
                        Picker("Playback", selection: $playback) { acceptanceOptions }
                        Picker("Visual / audio quality", selection: $perceptual) { acceptanceOptions }
                        Button("Record my review") { Task { await store.mutate("POST", "/jobs/\(item["job_id"].string)/acceptance", ["playback": .string(playback), "perceptual": .string(perceptual), "expected_revision": .number(Double(currentRevision))]) } }
                        Text("Record only what you have checked. Manual review is separate from technical verification and cleanup policy.").font(.caption).foregroundStyle(.secondary)
                    }.padding(8)
                }
                Button("Preview temporary-original cleanup") { Task { cleanupRevision = currentRevision; cleanup = await store.query("POST", "/jobs/\(item["job_id"].string)/cleanup-preview", [:]) ?? .null } }
                if cleanup != .null {
                    StructuredValueView(value: cleanup)
                    Button("Permanently delete eligible temporary originals…", role: .destructive) { confirmCleanup = true }.disabled(!cleanup["eligible"].bool || store.busy || cleanupRevision != currentRevision)
                }
                if !store.exports.isEmpty {
                    GroupBox("Transfers") {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(store.exports.filter { $0["job_id"].string == item["job_id"].string }, id: \.stableID) { transfer in
                                StructuredValueView(value: transfer)
                                HStack {
                                    Button("Pause") { transferAction(transfer, "pause") }
                                    Button("Resume") { transferAction(transfer, "resume") }
                                    Button("Stop now") { transferAction(transfer, "stop_now") }
                                }
                            }
                        }.padding(8)
                    }
                }
            }.padding(20)
        }.onAppear { playback = item["acceptance"]["playback"].string; perceptual = item["acceptance"]["perceptual"].string }
        .confirmationDialog("Permanently delete the listed temporary originals?", isPresented: $confirmCleanup) {
            Button("Delete eligible originals", role: .destructive) { Task {
                await store.mutate("POST", "/jobs/\(item["job_id"].string)/cleanup", ["expected_revision": .number(Double(cleanupRevision))])
            } }
        } message: { Text("Deletion is irreversible. Technical checks do not prove playback. Only listed app-created temporary originals are eligible; imported sources and verified deliverables remain.") }
    }
    private var currentRevision: Int { store.jobs.first { $0.id == item["job_id"].string }?.revision ?? 0 }
    @ViewBuilder private var acceptanceOptions: some View { Text("Pending").tag("pending"); Text("Accepted").tag("accepted"); Text("Rejected").tag("rejected") }
    private func transferAction(_ transfer: JSONValue, _ action: String) { Task { await store.mutate("POST", "/exports/\(transfer["id"].string)/action", ["action": .string(action), "expected_revision": transfer["revision"]]) } }
}
