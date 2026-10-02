import SwiftUI

struct QueueView: View {
    @Bindable var store: ArchiveStore
    @State private var search = ""
    @SceneStorage("queue.filter") private var filter = "all"
    private var jobs: [ArchiveJob] {
        store.jobs.filter {
            (filter == "all" || (filter == "finished" ? ["completed", "cancelled"].contains($0.state) : !["completed", "cancelled"].contains($0.state))) &&
            (search.isEmpty || $0.collection.localizedCaseInsensitiveContains(search) || $0.state.localizedCaseInsensitiveContains(search))
        }.sorted { ($0.queueOrder ?? 0) < ($1.queueOrder ?? 0) }
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Picker("Show jobs", selection: $filter) {
                    Text("All jobs").tag("all")
                    Text("In progress").tag("current")
                    Text("Finished").tag("finished")
                }.pickerStyle(.segmented).labelsHidden().frame(maxWidth: 310)
                Spacer()
                Text("\(jobs.count) \(jobs.count == 1 ? "job" : "jobs")").font(.caption).foregroundStyle(.secondary)
                if let job = store.selectedJob, job.state == "queued" {
                    Button { reorder(job, offset: -1) } label: { Image(systemName: "arrow.up") }
                        .help("Move earlier in queue").accessibilityLabel("Move earlier in queue").disabled(!canReorder(job, offset: -1) || store.busy)
                    Button { reorder(job, offset: 1) } label: { Image(systemName: "arrow.down") }
                        .help("Move later in queue").accessibilityLabel("Move later in queue").disabled(!canReorder(job, offset: 1) || store.busy)
                }
            }.padding(.horizontal, 20).padding(.vertical, 12)
            Divider()
            if store.jobs.isEmpty {
                ContentUnavailableView {
                    Label("Your queue is empty", systemImage: "list.bullet.rectangle")
                } description: {
                    Text("Add a disc or video from Discs to start an archive.")
                } actions: {
                    Button("Go to Discs") { store.destination = .discs }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if jobs.isEmpty {
                ContentUnavailableView("No matching jobs", systemImage: "magnifyingglass", description: Text("Try another search or choose All jobs."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VSplitView {
                    Table(jobs, selection: $store.selectedJobID) {
                        TableColumn("Archive") { job in
                            Label(job.collection, systemImage: job.kind == "series" ? "tv" : "opticaldisc").lineLimit(1)
                        }.width(min: 170, ideal: 260)
                        TableColumn("Status") { job in JobStatusLabel(job: job) }.width(min: 110, ideal: 140)
                        TableColumn("Progress") { job in
                            HStack(spacing: 8) {
                                ProgressView(value: min(max(job.progress, 0), 1)).controlSize(.small).accessibilityHidden(true)
                                Text(job.progress, format: .percent.precision(.fractionLength(0))).font(.caption).monospacedDigit().frame(width: 34, alignment: .trailing)
                            }.help("Progress counts saved title checkpoints")
                        }.width(min: 100, ideal: 140)
                        TableColumn("Current step") { job in
                            Text(job.currentTitle ?? Checkpoint(rawValue: job.phase)?.title ?? job.message).foregroundStyle(.secondary).lineLimit(1)
                        }.width(min: 130, ideal: 230)
                    }
                    .contextMenu(forSelectionType: String.self) { ids in
                        if let id = ids.first, let job = store.jobs.first(where: { $0.id == id }) {
                            Button("Move earlier") { reorder(job, offset: -1) }.disabled(!canReorder(job, offset: -1) || store.busy)
                            Button("Move later") { reorder(job, offset: 1) }.disabled(!canReorder(job, offset: 1) || store.busy)
                        }
                    }.frame(minHeight: 150, idealHeight: 230, maxHeight: .infinity)
                    Group {
                        if let job = store.selectedJob, jobs.contains(where: { $0.id == job.id }) { JobDetailView(store: store, job: job).id(job.id) }
                        else { ContentUnavailableView("Select a job", systemImage: "sidebar.bottom", description: Text("Choose an archive above to see progress and checkpoint controls.")) }
                    }.frame(maxWidth: .infinity, minHeight: 240, maxHeight: .infinity)
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
        .searchable(text: $search, prompt: "Search jobs")
        .onAppear { selectFirstIfNeeded() }
        .onChange(of: store.jobs.map(\.id)) { _, _ in selectFirstIfNeeded() }
    }
    private var queued: [String] { store.jobs.filter { $0.state == "queued" }.sorted { ($0.queueOrder ?? 0) < ($1.queueOrder ?? 0) }.map(\.id) }
    private func canReorder(_ job: ArchiveJob, offset: Int) -> Bool {
        guard let index = queued.firstIndex(of: job.id) else { return false }
        return queued.indices.contains(index + offset)
    }
    private func selectFirstIfNeeded() {
        if store.selectedJobID == nil || !store.jobs.contains(where: { $0.id == store.selectedJobID }) { store.selectedJobID = jobs.first?.id }
    }
    private func reorder(_ job: ArchiveJob, offset: Int) {
        var ids = queued
        guard let index = ids.firstIndex(of: job.id), ids.indices.contains(index + offset) else { return }
        ids.swapAt(index, index + offset); Task { await store.queue("reorder", ids: ids) }
    }
}

struct JobStatusLabel: View {
    let job: ArchiveJob
    private var symbol: String {
        switch job.state {
        case "completed": "checkmark.circle"
        case "running": "arrow.triangle.2.circlepath"
        case "queued": "clock"
        case "paused": "pause.circle"
        case "cancelled": "xmark.circle"
        default: "exclamationmark.circle"
        }
    }
    var body: some View {
        Label(job.state.replacingOccurrences(of: "_", with: " ").capitalized, systemImage: symbol)
            .font(.callout).foregroundStyle(job.state == "failed" || job.state == "blocked" ? Color.orange : Color.secondary)
            .lineLimit(1).help(job.message)
    }
}
