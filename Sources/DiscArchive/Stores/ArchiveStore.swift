import Foundation
import Observation

@MainActor @Observable
final class ArchiveStore {
    static let shared = ArchiveStore()
    var status: EngineStatus?
    var error: String?
    var busy = false
    var scanning = false
    var connected = false
    var reportText: String?
    @ObservationIgnored let client = EngineClient()
    @ObservationIgnored private var started = false

    var jobs: [ArchiveJob] { status?.jobs ?? [] }
    var discs: [ArchiveDisc] { status?.discs ?? [] }
    var safe: Bool { connected && status?.safeToDisconnect == true && !scanning && !busy }

    func watch() async {
        guard !started else { return }
        started = true
        defer { started = false }
        do { try await client.ensureRunning() }
        catch { self.error = error.localizedDescription }
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: .seconds(2))
        }
    }
    func refresh() async {
        do {
            status = try await client.get("/status", as: EngineStatus.self)
            connected = true
        } catch {
            connected = false
            self.error = error.localizedDescription
        }
    }
    func reconnect() async {
        await perform { try await self.client.ensureRunning() }
    }
    func scan() async {
        guard !scanning else { return }
        scanning = true
        defer { scanning = false }
        await perform { _ = try await self.client.post("/scan", body: [String: String](), as: ScanReply.self) }
    }
    func settings(_ settings: ArchiveSettings) async {
        await perform { _ = try await self.client.post("/settings", body: settings, as: ArchiveSettings.self) }
    }
    func start(_ request: JobRequest, saveProfile: Bool) async -> String? {
        busy = true
        defer { busy = false }
        do {
            // Commit job first. A rejected job must not teach an automatic disc profile.
            let job = try await client.post("/jobs", body: request, as: ArchiveJob.self)
            if saveProfile, let discID = request.discId {
                try await client.postDiscarding("/profiles", body: ProfileRequest(discId: discID,
                    collection: request.collection, kind: request.kind, titles: request.titles))
            }
            await refresh()
            return job.id
        } catch {
            self.error = error.localizedDescription
            await refresh()
            return nil
        }
    }
    func action(_ job: ArchiveJob, _ action: String, stopAfter: String? = nil) async {
        await perform { _ = try await self.client.post("/jobs/\(job.id)/action",
                        body: JobAction(action: action, stopAfter: stopAfter), as: ArchiveJob.self) }
    }
    func prepareToDisconnect() async {
        await perform {
            _ = try await self.client.post("/settings", body: ["auto_start": false], as: ArchiveSettings.self)
            for job in self.jobs where job.isActive {
                _ = try await self.client.post("/jobs/\(job.id)/action",
                    body: JobAction(action: "pause_after_checkpoint"), as: ArchiveJob.self)
            }
        }
    }
    func loadReport(_ job: ArchiveJob) async {
        await perform { self.reportText = try await self.client.report(job.id) }
    }
    private func perform(_ operation: () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do { try await operation(); await refresh() }
        catch { self.error = error.localizedDescription }
    }
}
