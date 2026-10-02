import Foundation
import Observation

@MainActor @Observable
final class ArchiveStore {
    static let shared = ArchiveStore()
    var status: EngineStatus?
    var capabilities: JSONValue = .null
    var presets: [JSONValue] = []
    var profiles: [JSONValue] = []
    var library: [JSONValue] = []
    var exports: [JSONValue] = []
    var events: [JSONValue] = []
    var destination: WorkspaceDestination = .discs
    var selectedJobID: String?
    var error: String?
    var busy = false
    var scanning = false
    var connected = false
    var reportText: String?
    var notificationAuthorization = "Checking permission…"
    @ObservationIgnored let client = EngineClient()
    @ObservationIgnored let notifier = ArchiveNotifier()
    @ObservationIgnored private var started = false
    @ObservationIgnored private var watchTask: Task<Void, Never>?
    @ObservationIgnored private var lastRefreshError: String?
    var jobs: [ArchiveJob] { status?.jobs ?? [] }
    var discs: [ArchiveDisc] { status?.discs ?? [] }
    var safe: Bool { connected && status?.safeToDisconnect == true && !scanning && !busy }
    var selectedJob: ArchiveJob? { jobs.first { $0.id == selectedJobID } }
    var schema: [String: JSONValue] { capabilities["settings_schema"].object }

    func startWatching() {
        guard watchTask == nil else { return }
        watchTask = Task { [weak self] in await self?.watch() }
    }
    func stopWatching() { watchTask?.cancel(); watchTask = nil }
    private func watch() async {
        guard !started else { return }
        started = true
        defer { started = false }
        await refreshNotificationAuthorization()
        do { try await client.ensureRunning(); capabilities = try await client.capabilities() }
        catch { self.error = error.localizedDescription }
        while !Task.isCancelled { await refresh(); try? await Task.sleep(for: .seconds(2)) }
    }
    func refresh() async {
        do {
            let fresh = try await client.get("/status", as: EngineStatus.self)
            status = fresh; connected = fresh.apiVersion == 2
            if let available = fresh.presets { presets = available }
            await notifier.observe(jobs: fresh.jobs, enabled: fresh.settings["notifications"].bool)
            notificationAuthorization = notifier.authorizationLabel
            guard connected else { return }
        } catch { connected = false; reportRefreshError(error.localizedDescription); return }
        do {
            if capabilities == .null { capabilities = try await client.capabilities() }
            if presets.isEmpty { presets = try await client.api("GET", "/presets")["presets"].array }
            switch destination {
            case .profiles:
                presets = try await client.api("GET", "/presets")["presets"].array
                profiles = try await client.api("GET", "/profiles")["profiles"].array
            case .library:
                library = try await client.api("GET", "/library")["items"].array
                exports = try await client.api("GET", "/exports")["exports"].array
            case .settings: presets = try await client.api("GET", "/presets")["presets"].array
            default: break
            }
            lastRefreshError = nil
        } catch { reportRefreshError(error.localizedDescription) }
    }
    private func reportRefreshError(_ message: String) {
        guard lastRefreshError != message else { return }
        lastRefreshError = message; error = message
    }
    func refreshNotificationAuthorization() async {
        await notifier.refreshAuthorization(force: true)
        notificationAuthorization = notifier.authorizationLabel
    }
    func authorizeNotifications() async {
        do { try await notifier.requestAuthorization(); notificationAuthorization = notifier.authorizationLabel }
        catch { self.error = error.localizedDescription }
    }
    func reconnect() async { await perform { try await self.client.ensureRunning(); self.capabilities = try await self.client.capabilities() } }
    func scan() async {
        guard !scanning else { return }; scanning = true
        defer { scanning = false }
        do {
            let start = try await self.client.api("POST", "/scans", body: [:])
            let id = start["id"].string
            guard !id.isEmpty else { throw ArchiveClientError.message("Scan did not return an identifier.") }
            for _ in 0..<240 {
                try Task.checkCancellation()
                let scan = try await self.client.api("GET", "/scans/\(id)")
                if ["completed", "failed", "cancelled"].contains(scan["state"].string) {
                    if scan["state"].string == "failed" { throw ArchiveClientError.message(scan["message"].string) }
                    await self.refresh(); return
                }
                try await Task.sleep(for: .seconds(1))
            }
            throw ArchiveClientError.message("Scan is taking longer than expected. Check Diagnostics before starting another scan.")
        } catch { self.error = error.localizedDescription }
        await refresh()
    }
    func settings(_ settings: ArchiveSettings, original: ArchiveSettings? = nil) async {
        let base = original ?? status?.settings ?? ArchiveSettings()
        var body = settings.changes(from: base); body["expected_revision"] = .number(Double(base.revision))
        await perform { _ = try await self.client.api("PATCH", "/settings", body: body) }
    }
    func start(_ request: JobRequest, saveProfile: Bool) async -> String? {
        guard !busy else { return nil }; busy = true; defer { busy = false }
        error = nil
        do {
            var request = request
            request.rememberProfile = saveProfile
            request.expectedSettingsRevision = status?.settings.revision
            request.idempotencyKey = request.idempotencyKey ?? UUID().uuidString
            let job = try await client.post("/jobs", body: request, as: ArchiveJob.self)
            selectedJobID = job.id; destination = .queue; await refresh(); return job.id
        } catch { self.error = error.localizedDescription; await refresh(); return nil }
    }
    func action(_ job: ArchiveJob, _ action: String, stopAfter: String? = nil) async {
        var body: [String: JSONValue] = ["action": .string(action), "expected_revision": .number(Double(job.revision ?? 0))]
        if let stopAfter { body["stop_after"] = .string(stopAfter) }
        await perform {
            let result = try await self.client.api("POST", "/jobs/\(job.id)/action", body: body)
            if result["reacquisition_needed"].bool { throw ArchiveClientError.message(result["reason"].string) }
            if action == "reprocess", !result["id"].string.isEmpty { self.selectedJobID = result["id"].string; self.destination = .queue }
        }
    }
    func queue(_ action: String, ids: [String]? = nil) async {
        var body: [String: JSONValue] = ["action": .string(action)]
        if let ids { body["job_ids"] = .strings(ids) }
        await mutate("POST", "/queue/action", body)
    }
    func prepareToDisconnect() async { await queue("prepare_disconnect") }
    func mutate(_ method: String, _ path: String, _ body: [String: JSONValue] = [:]) async {
        await perform { _ = try await self.client.api(method, path, body: body) }
    }
    func query(_ method: String, _ path: String, _ body: [String: JSONValue]? = nil) async -> JSONValue? {
        error = nil
        do { return try await client.api(method, path, body: body) }
        catch { self.error = error.localizedDescription; return nil }
    }
    func loadReport(_ job: ArchiveJob) async { await perform { self.reportText = try await self.client.report(job.id) } }
    private func perform(_ operation: () async throws -> Void) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        error = nil
        do { try await operation(); await refresh() }
        catch { self.error = error.localizedDescription }
    }
}
