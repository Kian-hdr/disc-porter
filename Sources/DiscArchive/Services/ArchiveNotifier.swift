import Foundation
import UserNotifications

@MainActor final class ArchiveNotifier: NSObject, UNUserNotificationCenterDelegate {
    var authorizationLabel = "Not requested"
    var openJob: (@MainActor @Sendable (String) -> Void)?
    private var tracker = NotificationTracker()
    private var authorized = false
    private var checkedAt: Date?
    private var sent: Set<String> = []
    private var pending: Set<String> = []
    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        sent = Set(defaults.stringArray(forKey: "discPorter.sentJobNotices") ?? [])
        super.init()
    }
    private var center: UNUserNotificationCenter? {
        guard Bundle.main.bundleIdentifier != nil, !ProcessInfo.processInfo.arguments.contains(where: { $0.hasSuffix(".xctest") }) else { return nil }
        let value = UNUserNotificationCenter.current(); value.delegate = self; return value
    }
    func refreshAuthorization(force: Bool = false) async {
        if !force, let checkedAt, Date().timeIntervalSince(checkedAt) < 30 { return }
        checkedAt = Date()
        guard let center else { authorized = false; authorizationLabel = "Available in the signed app bundle"; return }
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized: authorized = true; authorizationLabel = "Allowed by macOS"
        case .provisional: authorized = true; authorizationLabel = "Allowed quietly by macOS"
        case .denied: authorized = false; authorizationLabel = "Not allowed; change in macOS System Settings"
        case .notDetermined: authorized = false; authorizationLabel = "Not requested"
        default: authorized = false; authorizationLabel = "Unavailable"
        }
    }
    func requestAuthorization() async throws {
        guard let center else { throw ArchiveClientError.message("Open the signed Disc Porter app to authorize notifications.") }
        _ = try await center.requestAuthorization(options: [.alert, .sound])
        await refreshAuthorization(force: true)
    }
    func observe(jobs: [ArchiveJob], enabled: Bool) async {
        let changes = tracker.changes(jobs)
        await refreshAuthorization()
        guard enabled, authorized, let center else { return }
        for notice in changes where !sent.contains(notice.identifier) && !pending.contains(notice.identifier) {
            pending.insert(notice.identifier)
            let content = UNMutableNotificationContent()
            content.title = notice.completed ? "Archive complete" : "Archive needs attention"
            content.body = notice.completed ? "Technical verification finished. Playback review remains separate." : "Open Disc Porter to review the job and its next step."
            content.sound = .default
            content.userInfo = ["job_id": notice.jobID]
            do {
                try await center.add(UNNotificationRequest(identifier: notice.identifier, content: content, trigger: nil))
                sent.insert(notice.identifier)
                defaults.set(Array(sent).sorted().suffix(1000).map { $0 }, forKey: "discPorter.sentJobNotices")
            } catch { /* Notification failure does not change archive truth or interrupt processing. */ }
            pending.remove(notice.identifier)
        }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .list, .sound] }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        guard let id = response.notification.request.content.userInfo["job_id"] as? String else { return }
        await MainActor.run { self.openJob?(id) }
    }
}
