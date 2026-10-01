import SwiftUI
import AppKit
import ImageIO
import UniformTypeIdentifiers

/// Only reads the backend's cached image. Opening a book never makes a network request.
struct BookCoverView: View {
    let title: String
    let path: String?
    var width: CGFloat = 96
    var height: CGFloat = 144
    @State private var image: NSImage?
    private static let cache: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 160
        cache.totalCostLimit = 32 * 1024 * 1024
        return cache
    }()
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 5).fill(BridgePalette.secondarySurface)
            if let image {
                Image(nsImage: image).resizable().scaledToFit()
            } else {
                ZStack(alignment: .leading) {
                    LinearGradient(colors: [teal.opacity(0.24), teal.opacity(0.07)], startPoint: .topLeading, endPoint: .bottomTrailing)
                    Rectangle().fill(teal.opacity(0.15)).frame(width: 4)
                    VStack(spacing: 10) {
                        Image(systemName: "book.closed").font(.system(size: width < 50 ? 13 : 22, weight: .light))
                        if width >= 70 {
                            Text(title).font(.system(size: 12, weight: .medium, design: .serif)).multilineTextAlignment(.center).lineLimit(4)
                        }
                    }.padding(width < 50 ? 5 : 12).frame(maxWidth: .infinity, maxHeight: .infinity).foregroundStyle(teal)
                }
            }
        }
        .frame(width: width, height: height).clipShape(RoundedRectangle(cornerRadius: 5))
        .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(.primary.opacity(0.08)))
        .shadow(color: .black.opacity(0.12), radius: width < 50 ? 2 : 7, x: 0, y: 3)
        .accessibilityLabel(image == nil ? "No cover for \(title)" : "Cover of \(title)")
        .task(id: path) {
            image = nil
            guard let path, !path.isEmpty else { return }
            if let cached = Self.cache.object(forKey: path as NSString) { image = cached; return }
            let thumbnailData = await Task.detached(priority: .utility) { () -> Data? in
                let url = URL(fileURLWithPath: path)
                guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= 5 * 1024 * 1024,
                      let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                      let w = properties[kCGImagePropertyPixelWidth] as? Int,
                      let h = properties[kCGImagePropertyPixelHeight] as? Int,
                      w > 0, h > 0, w <= 8000, h <= 8000, w * h <= 24_000_000,
                      let cgImage = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                        kCGImageSourceCreateThumbnailFromImageAlways: true,
                        kCGImageSourceCreateThumbnailWithTransform: true,
                        kCGImageSourceThumbnailMaxPixelSize: 400
                      ] as CFDictionary) else { return nil }
                let data = NSMutableData()
                guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { return nil }
                CGImageDestinationAddImage(destination, cgImage, nil)
                guard CGImageDestinationFinalize(destination) else { return nil }
                return data as Data
            }.value
            guard !Task.isCancelled else { return }
            if let thumbnailData, let thumbnail = NSImage(data: thumbnailData) {
                Self.cache.setObject(thumbnail, forKey: path as NSString, cost: 400 * 400 * 4)
                image = thumbnail
            }
        }
    }
}

@MainActor func chooseBookCover(title: String, author: String, model: AppModel) {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = false; panel.canChooseFiles = true; panel.allowsMultipleSelection = false
    panel.allowedContentTypes = [.jpeg, .png, .epub]
    panel.message = "Choose a cover image or the EPUB for \(title). Applies to every highlight in this book."
    panel.prompt = "Use cover"
    if panel.runModal() == .OK, let path = panel.url?.path {
        Task { await model.perform("set_cover", ["path": path, "title": title, "author": author], activity: "Saving book cover…", success: "Book cover saved on this Mac.") }
    }
}
