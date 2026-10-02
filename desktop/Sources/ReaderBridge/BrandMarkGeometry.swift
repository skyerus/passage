import CoreGraphics

/// Passage's open book, with a visible spine and two layers of page edges.
/// The app and icon renderer share these paths, in a 1,000-point square.
enum BrandMarkGeometry {
    static let page: CGPath = {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: 208, y: 274))
        path.addLine(to: CGPoint(x: 456, y: 394))
        path.addQuadCurve(to: CGPoint(x: 472, y: 418), control: CGPoint(x: 472, y: 400))
        path.addLine(to: CGPoint(x: 472, y: 786))
        path.addQuadCurve(to: CGPoint(x: 465, y: 790), control: CGPoint(x: 472, y: 796))
        path.addLine(to: CGPoint(x: 208, y: 660))
        path.addQuadCurve(to: CGPoint(x: 198, y: 645), control: CGPoint(x: 198, y: 656))
        path.addLine(to: CGPoint(x: 198, y: 281))
        path.addQuadCurve(to: CGPoint(x: 208, y: 274), control: CGPoint(x: 198, y: 268))
        path.closeSubpath()
        return path
    }()

    static let otherPage: CGPath = {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: 516, y: 396))
        path.addLine(to: CGPoint(x: 804, y: 274))
        path.addQuadCurve(to: CGPoint(x: 814, y: 282), control: CGPoint(x: 814, y: 269))
        path.addLine(to: CGPoint(x: 814, y: 650))
        path.addQuadCurve(to: CGPoint(x: 804, y: 664), control: CGPoint(x: 814, y: 660))
        path.addLine(to: CGPoint(x: 516, y: 796))
        path.addQuadCurve(to: CGPoint(x: 506, y: 788), control: CGPoint(x: 506, y: 800))
        path.addLine(to: CGPoint(x: 506, y: 422))
        path.addQuadCurve(to: CGPoint(x: 516, y: 396), control: CGPoint(x: 506, y: 406))
        path.closeSubpath()
        return path
    }()

    static let pageEdges: CGPath = {
        let path = CGMutablePath()
        for offset in [CGFloat(0), 27] {
            path.move(to: CGPoint(x: 226 + offset, y: 248 - offset))
            path.addLine(to: CGPoint(x: 440, y: 352 - offset))
            path.addQuadCurve(to: CGPoint(x: 480, y: 383 - offset), control: CGPoint(x: 469, y: 367 - offset))
            path.addLine(to: CGPoint(x: 235 + offset, y: 266 - offset))
            path.addQuadCurve(to: CGPoint(x: 226 + offset, y: 260 - offset), control: CGPoint(x: 226 + offset, y: 266 - offset))
            path.closeSubpath()

            path.move(to: CGPoint(x: 784 - offset, y: 246 - offset))
            path.addLine(to: CGPoint(x: 548, y: 351 - offset))
            path.addQuadCurve(to: CGPoint(x: 500, y: 383 - offset), control: CGPoint(x: 514, y: 365 - offset))
            path.addLine(to: CGPoint(x: 784 - offset, y: 263 - offset))
            path.addQuadCurve(to: CGPoint(x: 791 - offset, y: 256 - offset), control: CGPoint(x: 791 - offset, y: 262 - offset))
            path.addLine(to: CGPoint(x: 791 - offset, y: 249 - offset))
            path.addQuadCurve(to: CGPoint(x: 784 - offset, y: 246 - offset), control: CGPoint(x: 791 - offset, y: 243 - offset))
            path.closeSubpath()
        }
        return path
    }()

    static let mark: CGPath = {
        let path = CGMutablePath()
        for part in [page, otherPage, pageEdges] { path.addPath(part) }
        return path
    }()
    static let bounds = mark.boundingBoxOfPath

    static func canvas(in size: CGSize) -> CGRect {
        let scale = min(size.width / bounds.width, size.height / bounds.height)
        return CGRect(x: (size.width - bounds.width * scale) / 2 - bounds.minX * scale,
                      y: (size.height - bounds.height * scale) / 2 - bounds.minY * scale,
                      width: 1000 * scale, height: 1000 * scale)
    }

    static func fitted(_ path: CGPath, in rect: CGRect) -> CGPath {
        var transform = CGAffineTransform(translationX: rect.minX, y: rect.minY)
            .scaledBy(x: rect.width / 1000, y: rect.height / 1000)
        return path.copy(using: &transform)!
    }
}
