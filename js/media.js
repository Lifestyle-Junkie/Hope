/*
  media.js
  Image paste / drop / preview for Hope
*/
(function () {
  function initMedia() {
    const ta = document.getElementById("chat-input");
    const dropZone = document.getElementById("dropZone");
    const imagePreview = document.getElementById("imagePreview");
    const previewImage = document.getElementById("previewImage");
    const removeImage = document.getElementById("removeImage");

    if (!ta || !dropZone || !imagePreview || !previewImage || !removeImage) {
      console.warn("[Media] Missing DOM elements");
      return;
    }

    function showImagePreview(base64Data) {
      previewImage.src = base64Data;
      imagePreview.classList.add("active");
    }

    function clearImagePreview() {
      previewImage.src = "";
      imagePreview.classList.remove("active");
      delete window.imageDataFromPaste;
      delete window.imageDataFromDrop;
    }

    window.showImagePreview = showImagePreview;
    window.clearImagePreview = clearImagePreview;

    removeImage.addEventListener("click", clearImagePreview);

    ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    });

    dropZone.addEventListener("dragover", () => dropZone.classList.add("drag-over"));
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));

    dropZone.addEventListener("drop", (e) => {
      dropZone.classList.remove("drag-over");
      const files = e.dataTransfer.files;
      if (files.length && files[0].type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          window.imageDataFromDrop = ev.target.result;
          showImagePreview(window.imageDataFromDrop);
        };
        reader.readAsDataURL(files[0]);
      }
    });

    ta.addEventListener("paste", (e) => {
      const items = (e.clipboardData || window.clipboardData).items;
      for (let item of items) {
        if (item.type.indexOf("image") === 0) {
          e.preventDefault();
          const blob = item.getAsFile();
          const reader = new FileReader();
          reader.onload = (ev) => {
            window.imageDataFromPaste = ev.target.result;
            showImagePreview(window.imageDataFromPaste);
          };
          reader.readAsDataURL(blob);
          break;
        }
      }
    });

    console.log("[Media] Ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMedia);
  } else {
    initMedia();
  }
})();
