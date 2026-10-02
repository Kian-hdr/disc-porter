import Foundation

struct JobNotice: Equatable, Sendable {
    let jobID: String
    let identifier: String
    let completed: Bool
}

/// The first snapshot is a baseline. Historical jobs do not trigger surprise notices.
struct NotificationTracker {
    private var previous: [String: String]?
    mutating func changes(_ jobs: [ArchiveJob]) -> [JobNotice] {
        let current = Dictionary(uniqueKeysWithValues: jobs.map { ($0.id, "\($0.generation ?? 1):\($0.state)") })
        defer { previous = current }
        guard let previous else { return [] }
        return jobs.compactMap { job in
            let key = current[job.id] ?? ""
            guard ["completed", "failed", "blocked"].contains(job.state), previous[job.id] != key else { return nil }
            return JobNotice(jobID: job.id, identifier: "disc-porter:\(job.id):\(key)", completed: job.state == "completed")
        }
    }
}
