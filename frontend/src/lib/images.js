// Prepares an image for the model. For text-dense images (documents/reports) resolution is
// critical — downscaling too far or JPEG artefacts make the model unable to read the digits and
// it MAKES THEM UP instead. So images within maxDim are sent ORIGINAL (lossless, source format),
// like OpenWebUI does; only oversized ones are scaled down, and then a PNG source stays PNG
// (lossless) while photos become high-quality JPEG.
export function fileToScaledDataUrl(file, maxDim = 2560) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => {
      const original = reader.result; // original bytes, source format (lossless)
      const img = new Image();
      img.onerror = reject;
      img.onload = () => {
        if (Math.max(img.width, img.height) <= maxDim) {
          resolve(original); // leave it alone → document/text legibility is preserved
          return;
        }
        const scale = maxDim / Math.max(img.width, img.height);
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0, w, h);
        const type = file.type === "image/png" ? "image/png" : "image/jpeg";
        resolve(canvas.toDataURL(type, 0.92));
      };
      img.src = original;
    };
    reader.readAsDataURL(file);
  });
}
