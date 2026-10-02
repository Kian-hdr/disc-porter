import SwiftUI
import AppKit

struct JobDetailView: View {
    let store: ArchiveStore
    let job: ArchiveJob
    @State private var stopAfter = Checkpoint.complete
    @State private var destructiveAction: String?
    @State private var showEditor = false
    @State private var report: JSONValue = .null
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack { Text(job.collection).font(.title2.weight(.semibold)); Spacer(); Text(job.state.replacingOccurrences(of: "_", with: " ").capitalized).foregroundStyle(.secondary) }
                Text(job.message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                GroupBox { JobProgressView(job: job).padding(10) }
                HStack {
                    if job.isActive {
                        Button("Pause at checkpoint") { Task { await store.action(job, "pause_after_checkpoint") } }
                        Button("Stop now") { destructiveAction = "stop_now" }
                    } else if job.canResume {
                        Button("Next checkpoint") { Task { await store.action(job, "next_checkpoint") } }
                        Picker("Until", selection: $stopAfter) { ForEach(Checkpoint.allCases) { Text(job.originalOnly && $0 == .encode ? "Originals preserved" : $0.title).tag($0) } }.frame(maxWidth: 210)
                        Button("Resume") { Task { await store.action(job, "resume", stopAfter: stopAfter.rawValue) } }.buttonStyle(.borderedProminent)
                        if ["failed", "blocked"].contains(job.state) { Button("Retry") { Task { await store.action(job, "retry") } } }
                        Button("Edit plan") { showEditor.toggle() }
                    }
                    if job.state == "completed" { Button("Edit retention or recipe") { showEditor.toggle() } }
                }.disabled(store.busy)
                if showEditor { JobPlanEditor(store: store, job: job) }
                DisclosureGroup("Saved checkpoints") {
                    ForEach(Checkpoint.allCases) { checkpoint in
                        CheckpointRow(checkpoint: checkpoint, committed: committed(checkpoint), active: job.isActive && job.phase == checkpoint.rawValue, originalOnly: job.originalOnly)
                    }.padding(.vertical, 4)
                    if let detail = job.checkpointDetail { StructuredValueView(value: detail) }
                }
                DisclosureGroup("Effective recipe") { StructuredValueView(value: .object(job.settings?.values ?? [:])) }
                GroupBox("Archive") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(job.outputPath).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        HStack {
                            Button("Reveal") { NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: job.outputPath) }
                            Button("Load report") { Task { report = await store.query("GET", "/report/\(job.id)") ?? .null } }
                            Button("Reprocess") { Task { await store.action(job, "reprocess") } }.disabled(job.isActive || store.busy)
                            if !["completed", "cancelled"].contains(job.state) { Button("Cancel", role: .destructive) { destructiveAction = "cancel" } }
                        }
                    }.padding(10)
                }
                if let artifact = job.artifacts?.first, let path = [artifact["final"].string, artifact["candidate"].string].first(where: { !$0.isEmpty }) {
                    DisclosureGroup("Media preview") { MediaPreviewView(path: path) }
                }
                if report != .null { GroupBox("Verification report") { StructuredValueView(value: report).padding(10) } }
                DisclosureGroup("Diagnostics") {
                    VStack(alignment: .leading, spacing: 6) {
                        LabeledContent("Job", value: job.id)
                        LabeledContent("Source", value: job.sourcePath)
                        LabeledContent("Revision", value: String(job.revision ?? 0))
                        LabeledContent("Last processing advance", value: job.lastProgressAt ?? "Not reported")
                        LabeledContent("Engine heartbeat", value: job.heartbeatAt ?? "Not reported")
                    }.font(.caption).textSelection(.enabled)
                }
            }.padding(20)
        }
        .confirmationDialog(destructiveAction == "stop_now" ? "Stop this phase now?" : "Cancel this job?", isPresented: Binding(get: { destructiveAction != nil }, set: { if !$0 { destructiveAction = nil } })) {
            Button(destructiveAction == "stop_now" ? "Stop now" : "Cancel job", role: .destructive) { if let action = destructiveAction { Task { await store.action(job, action) } }; destructiveAction = nil }
        } message: { Text(destructiveAction == "stop_now" ? "Owned processing tools stop safely. The unfinished phase restarts to a fresh candidate when resumed; completed files remain." : "Completed files remain. Cancellation takes effect at a checkpoint.") }
    }
    private func committed(_ checkpoint: Checkpoint) -> Bool {
        let all = Checkpoint.allCases
        guard let last = all.firstIndex(where: { $0.rawValue == job.checkpoint }), let index = all.firstIndex(of: checkpoint) else { return false }
        return index <= last
    }
}

private struct JobProgressView: View {
    let job: ArchiveJob
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack { Text("Entire job").font(.headline); Spacer(); Text(job.progress, format: .percent.precision(.fractionLength(0))).monospacedDigit() }
            ProgressView(value: min(max(job.progress, 0), 1)).accessibilityLabel("Completed title checkpoint progress")
            Text(job.progressBasis ?? "Completed durable title checkpoints").font(.caption).foregroundStyle(.secondary)
            HStack {
                Text(phaseTitle).fontWeight(.medium); Spacer()
                if let progress = job.phaseProgress { Text(progress, format: .percent.precision(.fractionLength(0))).monospacedDigit() }
                else { Text(job.isActive ? "Measuring…" : job.state.capitalized).foregroundStyle(.secondary) }
            }
            if let progress = job.phaseProgress { ProgressView(value: min(max(progress, 0), 1)).accessibilityLabel("Measured subtask progress") }
            else if job.isActive { ProgressView().controlSize(.small) }
            if let title = job.currentTitle { Text(title).font(.callout).foregroundStyle(.secondary) }
            HStack(spacing: 14) {
                if let completed = job.completedItems, let total = job.totalItems { Text("This phase: \(completed) / \(total) titles") }
                if let elapsed = job.elapsedSeconds { Text("Elapsed \(duration(elapsed))") }
                if let speed = job.throughputBps, speed > 0 { Text(String(format: "%.1f MB/s", speed / 1_000_000)) }
                if let eta = job.etaSeconds, eta > 0 { Text("About \(duration(eta)) left") }
            }.font(.caption).foregroundStyle(.secondary).monospacedDigit()
            if let detail = job.checkpointDetail, !detail["phase"].string.isEmpty {
                Text("Last saved: \(job.originalOnly && detail["phase"].string == "encode" ? "Originals preserved" : Checkpoint(rawValue: detail["phase"].string)?.title ?? detail["phase"].string) · title \(detail["title_id"].display)").font(.caption).foregroundStyle(.secondary)
            }
            if let stamp = job.lastProgressAt, let date = parsedDate(stamp) {
                TimelineView(.periodic(from: .now, by: 5)) { context in Text("Last measured advance \(duration(context.date.timeIntervalSince(date))) ago").font(.caption).foregroundStyle(.secondary) }
            }
            if job.pauseRequested == true { Label("Pause requested at the next durable title checkpoint", systemImage: "pause.circle").font(.callout).foregroundStyle(.orange) }
            if let reason = job.stallReason, !reason.isEmpty { Label(reason, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange) }
        }
    }
    private var phaseTitle: String {
        switch job.phase { case "scan": "Identifying"; case "acquire": "Saving originals"; case "encode": job.originalOnly ? "Preserving originals" : "Encoding"; case "verify": "Verifying files"; default: "Finishing archive" }
    }
    private func duration(_ seconds: Double) -> String {
        let n = max(0, Int(seconds)); if n >= 3600 { return "\(n / 3600)h \((n % 3600) / 60)m" }; if n >= 60 { return "\(n / 60)m \(n % 60)s" }; return "\(n)s"
    }
    private func parsedDate(_ stamp: String) -> Date? {
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: stamp) ?? ISO8601DateFormatter().date(from: stamp)
    }
}

private struct CheckpointRow: View {
    let checkpoint: Checkpoint
    let committed: Bool
    let active: Bool
    var originalOnly = false
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: committed ? "checkmark.circle.fill" : active ? "arrow.trianglehead.2.clockwise.rotate.90" : "circle")
                .foregroundStyle(committed ? Color.green : active ? Color.accentColor : Color.secondary)
                .font(.title3).frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(originalOnly && checkpoint == .encode ? "Originals preserved" : checkpoint.title).font(.headline)
                Text(originalOnly && checkpoint == .encode ? "Original archive requires no lossy encode." : checkpoint.explanation).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if committed { Text("Saved").font(.caption).foregroundStyle(.green) }
            else if active { Text("In progress").font(.caption).foregroundStyle(.secondary) }
        }.accessibilityElement(children: .combine)
    }
}
