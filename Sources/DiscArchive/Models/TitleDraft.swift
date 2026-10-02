import Foundation

struct TitleDraft: Identifiable {
    let id: Int
    var selected: Bool
    var name: String
    var duration: String = ""
    var season: String = ""
    var episode: String = ""
    var year: String = ""
    var audioIDs: Set<Int> = []
    var subtitleIDs: Set<Int> = []
    var manualAudio = false
    var manualSubtitles = false
    var defaultAudioID: Int? = nil
    var defaultSubtitleID: Int? = nil
    var overrideForced = false
    var forcedIDs: Set<Int> = []
    var streams: [JSONValue] = []
    var overrides: ArchiveSettings? = nil
    var metadataValid: Bool { [season, year].allSatisfy { $0.isEmpty || Int($0).map { $0 >= 0 } == true } && (episode.isEmpty || Int(episode).map { $0 >= 1 } == true) }
    var title: ArchiveTitle {
        var result = ArchiveTitle(id: id, name: name)
        result.overrides = overrides
        if manualAudio { var recipe = result.overrides ?? ArchiveSettings(); recipe["audio_policy"] = .string("selected"); result.overrides = recipe }
        result.defaultAudioStream = defaultAudioID
        result.defaultSubtitleStream = defaultSubtitleID
        result.forcedSubtitleStreams = overrideForced ? forcedIDs.sorted() : nil
        result.audioStreams = manualAudio ? audioIDs.sorted() : nil
        result.subtitleStreams = manualSubtitles ? subtitleIDs.sorted() : nil
        result.season = Int(season); result.episode = Int(episode); result.year = Int(year)
        return result
    }
}
