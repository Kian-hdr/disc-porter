import SwiftUI

struct QueueView: View {
    @Bindable var store: ArchiveStore
    @State private var search = ""
    var jobs: [ArchiveJob] { store.jobs.filter { search.isEmpty || $0.collection.localizedCaseInsensitiveContains(search) || $0.state.localizedCaseInsensitiveContains(search) }.sorted { ($0.queueOrder ?? 0) < ($1.queueOrder ?? 0) } }
    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                List(selection: $store.selectedJobID) {
                    ForEach(jobs) { job in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack { Text(job.collection).fontWeight(.medium); Spacer(); Text(job.state.replacingOccurrences(of: "_", with: " ").capitalized).font(.caption).foregroundStyle(.secondary) }
                            if job.isActive { ProgressView(value: job.phaseProgress ?? job.progress).controlSize(.small) }
                            Text(job.currentTitle ?? job.message).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }.padding(.vertical, 3).tag(job.id)
                            .contextMenu {
                                Button("Move earlier") { reorder(job, offset: -1) }.disabled(job.state != "queued")
                                Button("Move later") { reorder(job, offset: 1) }.disabled(job.state != "queued")
                            }
                    }
                }
                if store.jobs.isEmpty { Text("Create an archive from Discs to begin.").font(.caption).foregroundStyle(.secondary).padding() }
            }.frame(minWidth: 260, idealWidth: 340, maxWidth: 440)
            if let job = store.selectedJob { JobDetailView(store: store, job: job).id(job.id) }
            else { ContentUnavailableView("Archive queue", systemImage: "list.bullet.rectangle", description: Text("Select a job to inspect progress, edit its next steps or review its report.")) }
        }.searchable(text: $search, prompt: "Search jobs")
    }
    private func reorder(_ job: ArchiveJob, offset: Int) {
        var queued = store.jobs.filter { $0.state == "queued" }.sorted { ($0.queueOrder ?? 0) < ($1.queueOrder ?? 0) }.map(\.id)
        guard let i = queued.firstIndex(of: job.id) else { return }
        let other = i + offset
        guard queued.indices.contains(other) else { return }
        queued.swapAt(i, other); Task { await store.queue("reorder", ids: queued) }
    }
}
