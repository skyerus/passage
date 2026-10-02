import Foundation

enum BookSort: String, CaseIterable, Identifiable {
    case recent, title, author, highlights

    var id: String { rawValue }
    var label: String {
        switch self {
        case .recent: return "Most recent"
        case .title: return "Title A–Z"
        case .author: return "Author A–Z"
        case .highlights: return "Most highlights"
        }
    }

    func sorted(_ books: [BookSummary]) -> [BookSummary] {
        books.sorted { lhs, rhs in
            switch self {
            case .recent:
                switch (lhs.latestHighlightAt, rhs.latestHighlightAt) {
                case let (left?, right?) where left != right: return left > right
                case (_?, nil): return true
                case (nil, _?): return false
                default: break
                }
            case .author:
                if lhs.author.isEmpty != rhs.author.isEmpty { return !lhs.author.isEmpty }
                let comparison = lhs.author.localizedStandardCompare(rhs.author)
                if comparison != .orderedSame { return comparison == .orderedAscending }
            case .highlights:
                if lhs.count != rhs.count { return lhs.count > rhs.count }
            case .title: break
            }
            let title = lhs.title.localizedStandardCompare(rhs.title)
            if title != .orderedSame { return title == .orderedAscending }
            let author = lhs.author.localizedStandardCompare(rhs.author)
            if author != .orderedSame { return author == .orderedAscending }
            return lhs.id < rhs.id
        }
    }
}
