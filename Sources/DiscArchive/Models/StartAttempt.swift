import Foundation

/// Keeps a transport key through an ambiguous failure of the same accepted plan.
struct StartAttempt: Equatable {
    private(set) var planFingerprint: String?
    private(set) var idempotencyKey: String?
    mutating func key(for plan: String) -> String {
        if planFingerprint == plan, let key = idempotencyKey { return key }
        let key = UUID().uuidString
        planFingerprint = plan; idempotencyKey = key
        return key
    }
    mutating func completed() { planFingerprint = nil; idempotencyKey = nil }
}
