import SwiftUI
import AppKit

struct JobDetailView: View {
    let store: ArchiveStore
    let job: ArchiveJob
    @State private var stopAfter = Checkpoint.complete
    @State private var showCancel = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(job.collection).font(.largeTitle.bold())
                        Text("\(job.kind.capitalized) · \(job.titles.count) selected title\(job.titles.count == 1 ? "" : "s")")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(job.state.capitalized).font(.headline).padding(.horizontal, 14).padding(.vertical, 8)
                        .background(.quaternary, in: Capsule())
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 12) {
                        JobProgressView(job: job)
                        Text(job.message).foregroundStyle(.secondary).textSelection(.enabled)
                        if job.isActive {
                            Button("Stop after the next checkpoint") { Task { await store.action(job, "pause_after_checkpoint") } }
                                .disabled(store.busy)
                        } else if job.canResume {
                            HStack {
                                Button("Work to next checkpoint") { Task { await store.action(job, "next_checkpoint") } }
                                Spacer()
                                Picker("Continue until", selection: $stopAfter) {
                                    ForEach(Checkpoint.allCases.filter { $0 != .scan }) { Text($0.title).tag($0) }
                                }.frame(width: 290)
                                Button("Resume") { Task { await store.action(job, "resume", stopAfter: stopAfter.rawValue) } }
                                    .buttonStyle(.borderedProminent)
                            }.disabled(store.busy)
                        }
                    }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
                }
                VStack(alignment: .leading, spacing: 16) {
                    Text("Saved checkpoints").font(.title3.bold())
                    ForEach(Checkpoint.allCases) { checkpoint in
                        CheckpointRow(checkpoint: checkpoint, committed: committed(checkpoint), active: job.isActive && job.phase == checkpoint.rawValue)
                    }
                }
                Divider()
                VStack(alignment: .leading, spacing: 10) {
                    Text("Archive location").font(.headline)
                    Text(job.outputPath).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                    HStack {
                        Button("Show in Finder") { NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: job.outputPath) }
                        Button("Verification report") { Task { await store.loadReport(job) } }
                        Spacer()
                        if job.state != "completed" && job.state != "cancelled" {
                            Button("Cancel job", role: .destructive) { showCancel = true }.disabled(store.busy)
                        }
                    }
                }
                Text("Originals are retained. Automatic checks verify file structure and decoding; review the actual content and target-player playback before considering an archive fully accepted.")
                    .font(.caption).foregroundStyle(.secondary)
                DisclosureGroup("Diagnostics") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Job: \(job.id)")
                        Text("Source: \(job.sourcePath)")
                        Text("Last progress event: \(job.lastProgressAt ?? "No measured progress yet")")
                        Text("Engine heartbeat: \(job.heartbeatAt ?? "Not reported")")
                        Text("Overall basis: \(job.progressBasis ?? "Completed checkpoints; phases take different amounts of time")")
                    }.font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
                }
            }.padding(28).frame(maxWidth: 850, alignment: .leading).frame(maxWidth: .infinity)
        }
        .navigationTitle(job.collection)
        .confirmationDialog("Cancel this job?", isPresented: $showCancel, titleVisibility: .visible) {
            Button("Cancel job", role: .destructive) { Task { await store.action(job, "cancel") } }
        } message: { Text("Finishes the active phase before cancelling. Completed originals, candidates and checkpoints remain saved.") }
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
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Entire job").font(.headline)
                Spacer()
                Text("\(completedCheckpoints) of 5 checkpoints saved").font(.caption).foregroundStyle(.secondary)
            }
            ProgressView(value: min(max(job.progress, 0), 1))
                .accessibilityLabel("Overall completed checkpoint progress")
            Text("Checkpoint-based progress. Scanning, ripping and encoding take different amounts of time.")
                .font(.caption).foregroundStyle(.secondary)
            Divider()
            HStack {
                Text(phaseTitle).font(.headline)
                Spacer()
                if let progress = job.phaseProgress {
                    Text(progress, format: .percent.precision(.fractionLength(0))).monospacedDigit()
                } else { Text(job.isActive ? "Measuring…" : job.state.capitalized).font(.caption).foregroundStyle(.secondary) }
            }
            if let progress = job.phaseProgress {
                ProgressView(value: min(max(progress, 0), 1)).accessibilityLabel("Current subtask measured progress")
            } else if job.isActive {
                ProgressView().controlSize(.small).accessibilityLabel("Subtask total is unknown")
            }
            if let title = job.currentTitle, !title.isEmpty { Text(title).font(.callout).foregroundStyle(.secondary) }
            HStack(spacing: 20) {
                if let completed = job.completedItems, let total = job.totalItems {
                    Text("\(completed) / \(total) titles").font(.caption)
                }
                if let elapsed = job.elapsedSeconds { Text("Subtask elapsed \(duration(elapsed))").font(.caption) }
                if let speed = job.throughputBps, speed > 0 {
                    Text("Output \(String(format: "%.1f", speed / 1_000_000)) MB/s").font(.caption)
                }
                if let eta = job.etaSeconds, eta > 0 { Text("Estimated \(duration(eta)) left").font(.caption) }
            }.foregroundStyle(.secondary).monospacedDigit()
            if let reason = job.stallReason, !reason.isEmpty {
                Label(reason, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            }
            if job.isActive {
                Text(job.pauseRequested == true ? "Pause requested. Finishing the next checkpoint: \(nextTitle)." : "Next checkpoint: \(nextTitle)")
                    .font(.callout).foregroundStyle(job.pauseRequested == true ? Color.orange : Color.secondary)
                if let stamp = job.lastProgressAt {
                    Text("Last processing advance: \(stamp)").font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("Waiting for the first measurable progress event. A responsive engine alone does not show that media is advancing.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }
    private var completedCheckpoints: Int {
        guard let index = Checkpoint.allCases.firstIndex(where: { $0.rawValue == job.checkpoint }) else { return 0 }
        return index + 1
    }
    private var phaseTitle: String {
        switch job.phase {
        case "scan": "Scanning"
        case "acquire": "Saving originals"
        case "encode": "Encoding"
        case "verify": "Verifying files"
        default: "Finishing archive"
        }
    }
    private var nextTitle: String {
        Checkpoint(rawValue: job.nextCheckpoint ?? job.phase)?.title ?? job.phase.capitalized
    }
    private func duration(_ seconds: Double) -> String {
        let n = max(0, Int(seconds))
        if n >= 3600 { return "\(n / 3600)h \((n % 3600) / 60)m" }
        if n >= 60 { return "\(n / 60)m \(n % 60)s" }
        return "\(n)s"
    }
}

private struct CheckpointRow: View {
    let checkpoint: Checkpoint
    let committed: Bool
    let active: Bool
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: committed ? "checkmark.circle.fill" : active ? "arrow.trianglehead.2.clockwise.rotate.90" : "circle")
                .foregroundStyle(committed ? Color.green : active ? Color.accentColor : Color.secondary)
                .font(.title3).frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(checkpoint.title).font(.headline)
                Text(checkpoint.explanation).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if committed { Text("Saved").font(.caption).foregroundStyle(.green) }
            else if active { Text("In progress").font(.caption).foregroundStyle(.secondary) }
        }.accessibilityElement(children: .combine)
    }
}
