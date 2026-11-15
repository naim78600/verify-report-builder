// Reads the text of a photo with macOS' own Vision framework (offline, free). Usage: mac_ocr <image>
// Prints the lines top to bottom. Exit 2 = image not readable, 3 = OCR failed.
import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count > 1 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
      let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { exit(2) }
var orient = CGImagePropertyOrientation.up
if let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
   let raw = props[kCGImagePropertyOrientation] as? UInt32,
   let o = CGImagePropertyOrientation(rawValue: raw) { orient = o }

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
do {
    try VNImageRequestHandler(cgImage: img, orientation: orient, options: [:]).perform([req])
} catch { exit(3) }

let obs = (req.results ?? []).sorted { $0.boundingBox.midY > $1.boundingBox.midY }
var lines: [[VNRecognizedTextObservation]] = []
for o in obs {                       // join boxes that sit on the same line, left to right
    if let last = lines.last, abs(last[0].boundingBox.midY - o.boundingBox.midY) < 0.012 { lines[lines.count - 1].append(o) }
    else { lines.append([o]) }
}
for l in lines {
    print(l.sorted { $0.boundingBox.minX < $1.boundingBox.minX }
           .compactMap { $0.topCandidates(1).first?.string }.joined(separator: "  "))
}
