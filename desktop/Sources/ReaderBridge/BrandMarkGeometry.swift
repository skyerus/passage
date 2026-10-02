import CoreGraphics

/// Original Reader Bridge mark: two open pages span a bridge arch.
/// The app and icon renderer share these paths, in a 1,000-point square.
enum BrandMarkGeometry {
    static let page: CGPath = {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: 164, y: 320))
        path.addCurve(to: CGPoint(x: 484, y: 400),
                      control1: CGPoint(x: 286, y: 274), control2: CGPoint(x: 414, y: 304))
        path.addLine(to: CGPoint(x: 484, y: 500))
        path.addCurve(to: CGPoint(x: 240, y: 690),
                      control1: CGPoint(x: 363, y: 509), control2: CGPoint(x: 283, y: 588))
        path.addLine(to: CGPoint(x: 164, y: 660))
        path.closeSubpath()
        return path
    }()

    static let otherPage: CGPath = {
        var mirror = CGAffineTransform(a: -1, b: 0, c: 0, d: 1, tx: 1000, ty: 0)
        return page.copy(using: &mirror)!
    }()

    static let bookmark: CGPath = {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: 484, y: 416))
        path.addLine(to: CGPoint(x: 516, y: 416))
        path.addLine(to: CGPoint(x: 516, y: 575))
        path.addLine(to: CGPoint(x: 500, y: 561))
        path.addLine(to: CGPoint(x: 484, y: 575))
        path.closeSubpath()
        return path
    }()

    static let bounds = page.boundingBoxOfPath.union(otherPage.boundingBoxOfPath)

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
