import SwiftUI

struct StructuredValueView: View {
    let value: JSONValue
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            switch value {
            case .object(let object):
                ForEach(object.keys.filter { !$0.hasPrefix("_") && !["source_probe", "disc_streams", "command", "tool_paths", "source_identity", "destination_identity"].contains($0) }.sorted(), id: \.self) { key in
                    StructuredRow(label: fieldLabel(key), value: object[key] ?? .null)
                }
            case .array(let array):
                ForEach(array, id: \.stableID) { item in StructuredRow(label: item["title"].string.isEmpty ? "Details" : item["title"].string, value: item) }
            default: Text(value.display).textSelection(.enabled)
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
private struct StructuredRow: View {
    let label: String
    let value: JSONValue
    var body: some View {
        if !value.object.isEmpty || !value.array.isEmpty && value.array.contains(where: { !$0.object.isEmpty }) {
            DisclosureGroup(label) { StructuredValueView(value: value).padding(.leading, 8) }
        } else {
            LabeledContent(label) { Text(value.display).foregroundStyle(.secondary).textSelection(.enabled).multilineTextAlignment(.trailing) }
        }
    }
}
