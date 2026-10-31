// ScanMatch - Frontend Controller (Direct Text Input & Cloud Vision Document OCR)

document.addEventListener("DOMContentLoaded", () => {
  // Elements: Tabs & Panels
  const tabDirectText = document.getElementById("tabDirectText");
  const tabUploadDoc = document.getElementById("tabUploadDoc");
  const panelDirect = document.getElementById("panelDirect");
  const panelUpload = document.getElementById("panelUpload");
  const modeBanner = document.getElementById("modeBanner");
  const bannerIcon = document.getElementById("bannerIcon");
  const bannerText = document.getElementById("bannerText");

  // Elements: Direct Text Form
  const directTextForm = document.getElementById("directTextForm");
  const shoppingListText = document.getElementById("shoppingListText");
  const clearTextBtn = document.getElementById("clearTextBtn");
  const submitTextBtn = document.getElementById("submitTextBtn");
  const btnTextSpinner = document.getElementById("btnTextSpinner");
  const submitTextLabel = document.getElementById("submitTextLabel");
  const chipButtons = document.querySelectorAll(".chip-btn");

  // Elements: Catalog Drawer
  const toggleCatalogBtn = document.getElementById("toggleCatalogBtn");
  const catalogModal = document.getElementById("catalogModal");
  const closeCatalogBtn = document.getElementById("closeCatalogBtn");
  const catalogSearchInput = document.getElementById("catalogSearchInput");
  const catalogGrid = document.getElementById("catalogGrid");

  // Elements: Document Upload Form
  const uploadForm = document.getElementById("uploadForm");
  const fileInput = document.getElementById("fileInput");
  const dropZone = document.getElementById("dropZone");
  const fileInfo = document.getElementById("fileInfo");
  const fileNameDisplay = document.getElementById("fileNameDisplay");
  const clearFileBtn = document.getElementById("clearFileBtn");
  const submitBtn = document.getElementById("submitBtn");
  const btnSpinner = document.getElementById("btnSpinner");
  const btnText = document.getElementById("btnText");

  // Elements: Cloud Vision Config
  const cloudVisionApiKey = document.getElementById("cloudVisionApiKey");
  const toggleApiKeyBtn = document.getElementById("toggleApiKeyBtn");

  // Elements: Alerts & Results
  const errorAlert = document.getElementById("errorAlert");
  const errorCode = document.getElementById("errorCode");
  const errorMessage = document.getElementById("errorMessage");

  const resultsSection = document.getElementById("resultsSection");
  const summaryTotal = document.getElementById("summaryTotal");
  const summaryMatched = document.getElementById("summaryMatched");
  const summaryReview = document.getElementById("summaryReview");
  const summaryUnidentified = document.getElementById("summaryUnidentified");
  const resultModeBadge = document.getElementById("resultModeBadge");
  const timingBadge = document.getElementById("timingBadge");
  const resultTableBody = document.getElementById("resultTableBody");
  const rawOcrText = document.getElementById("rawOcrText");
  const editExtractedBtn = document.getElementById("editExtractedBtn");

  let activeFile = null;
  let catalogProducts = [];

  // Pre-configured Quick Examples
  const SAMPLES = {
    gujarati: "ચોખા ૫ કિલો\nતેલ ૧ લિટર\nમીઠું ૧ પેકેટ\nખાંડ ૨ કિલો\nતુવેર દાળ ૫૦૦ ગ્રામ\nસાબુ ૪",
    hindi: "चावल 2 किलो\nतेल 1 लीटर\nनमक 1 पैकेट\nआटा 5 किलो\nदूध 1 लीटर\nचाय 500 ग्राम",
    english: "Rice 2 kg\nCooking Oil 1 liter\nSalt 1 packet\nSugar 1 kg\nToor Dal 500 g\nMilk 1 liter",
    mixed: "5 kg ચોખા\nWheat 5 kg\nતેલ ૧ લિટર\n2 kg चीनी\nMilk 1 liter\n1 packet salt",
  };

  // Load saved Cloud Vision API Key from localStorage
  const savedApiKey = localStorage.getItem("scanmatch_cloud_vision_key") || "";
  if (cloudVisionApiKey && savedApiKey) {
    cloudVisionApiKey.value = savedApiKey;
  }

  // Tab Switching
  function switchTab(tab) {
    hideError();

    if (tab === "direct") {
      tabDirectText.classList.add("active");
      tabUploadDoc.classList.remove("active");
      panelDirect.classList.add("active");
      panelUpload.classList.remove("active");

      modeBanner.className = "demo-banner banner-direct";
      bannerIcon.textContent = "✍️";
      bannerText.innerHTML = "<strong>Direct Text Mode:</strong> Type or paste your own shopping items directly. The C matching engine parses quantities, units, and multilingual product names with zero latency.";
    } else {
      tabUploadDoc.classList.add("active");
      tabDirectText.classList.remove("active");
      panelUpload.classList.add("active");
      panelDirect.classList.remove("active");

      modeBanner.className = "demo-banner banner-cloud";
      bannerIcon.textContent = "☁️";
      bannerText.innerHTML = "<strong>Google Cloud Vision OCR:</strong> Upload handwritten or printed shopping list documents (JPG, PNG, WEBP, PDF). Text is extracted via Google Cloud Vision and matched against the product catalog using the high-performance C matching engine.";
    }
  }

  tabDirectText.addEventListener("click", () => switchTab("direct"));
  tabUploadDoc.addEventListener("click", () => switchTab("upload"));

  // Toggle API Key Visibility
  toggleApiKeyBtn.addEventListener("click", () => {
    if (cloudVisionApiKey.type === "password") {
      cloudVisionApiKey.type = "text";
      toggleApiKeyBtn.textContent = "🔒";
    } else {
      cloudVisionApiKey.type = "password";
      toggleApiKeyBtn.textContent = "👁️";
    }
  });

  // Save API Key on input change
  cloudVisionApiKey.addEventListener("input", (e) => {
    localStorage.setItem("scanmatch_cloud_vision_key", e.target.value.trim());
  });

  // Quick Sample Buttons
  chipButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const sampleKey = btn.getAttribute("data-sample");
      if (SAMPLES[sampleKey]) {
        shoppingListText.value = SAMPLES[sampleKey];
        shoppingListText.focus();
      }
    });
  });

  // Clear Text Button
  clearTextBtn.addEventListener("click", () => {
    shoppingListText.value = "";
    shoppingListText.focus();
    hideError();
  });

  // Direct Text Form Submission
  directTextForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = shoppingListText.value.trim();

    if (!text) {
      showError("INPUT_REQUIRED", "Please type or paste at least one shopping list item.");
      return;
    }

    setTextLoading(true);
    hideError();

    const formData = new FormData();
    formData.append("text_input", text);

    try {
      const response = await fetch("/api/scan", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        const err = data.error || { code: "ERROR", message: "Matching processing failed." };
        showError(err.code || "REQUEST_FAILED", err.message || "Server returned an error.");
        resultsSection.classList.add("hidden");
      } else {
        renderResults(data);
      }
    } catch (err) {
      showError("NETWORK_ERROR", "Unable to connect to the ScanMatch server: " + err.message);
      resultsSection.classList.add("hidden");
    } finally {
      setTextLoading(false);
    }
  });

  // File selection helper
  function setFile(file) {
    activeFile = file;
    if (file) {
      fileNameDisplay.textContent = file.name + (file.size ? ` (${(file.size / 1024).toFixed(1)} KB)` : "");
      fileInfo.classList.remove("hidden");
      submitBtn.removeAttribute("disabled");
      hideError();
    } else {
      fileInfo.classList.add("hidden");
      submitBtn.setAttribute("disabled", "true");
      fileInput.value = "";
    }
  }

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  });

  clearFileBtn.addEventListener("click", () => {
    setFile(null);
  });

  // Drag and Drop
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("dragover");
    }, false);
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
    }, false);
  });

  dropZone.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length > 0) {
      setFile(dt.files[0]);
    }
  });

  // Document Upload Submit Handler
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeFile) return;

    setFileLoading(true);
    hideError();

    const formData = new FormData();
    formData.append("file", activeFile);

    const key = cloudVisionApiKey.value.trim();
    if (key) {
      formData.append("api_key", key);
    }

    try {
      const response = await fetch("/api/scan", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        const err = data.error || { code: "ERROR", message: "Scan processing failed." };
        showError(err.code || "REQUEST_FAILED", err.message || "Server returned an error.");
        resultsSection.classList.add("hidden");
      } else {
        renderResults(data);
      }
    } catch (err) {
      showError("NETWORK_ERROR", "Unable to connect to the ScanMatch server: " + err.message);
      resultsSection.classList.add("hidden");
    } finally {
      setFileLoading(false);
    }
  });

  // Edit in Text Mode Action
  editExtractedBtn.addEventListener("click", () => {
    const currentText = rawOcrText.textContent || "";
    if (currentText && currentText !== "(No text returned)") {
      shoppingListText.value = currentText;
      switchTab("direct");
      shoppingListText.focus();
      shoppingListText.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });

  // Render Matching Results
  function renderResults(data) {
    const summary = data.summary || {
      total_items: 0,
      confirmed_items: 0,
      needs_confirmation: 0,
      unidentified_items: 0,
    };

    summaryTotal.textContent = summary.total_items;
    summaryMatched.textContent = summary.confirmed_items;
    summaryReview.textContent = summary.needs_confirmation;
    summaryUnidentified.textContent = summary.unidentified_items;

    // Mode badge
    if (data.mode === "direct_text") {
      resultModeBadge.textContent = "Direct Text Input";
      resultModeBadge.style.color = "#34d399";
    } else {
      resultModeBadge.textContent = "Google Cloud Vision";
      resultModeBadge.style.color = "#38bdf8";
    }

    // Timings
    if (data.timings_ms) {
      timingBadge.textContent = `OCR: ${data.timings_ms.ocr}ms | Match: ${data.timings_ms.matching}ms | Total: ${data.timings_ms.total}ms`;
    }

    rawOcrText.textContent = data.ocr_text || "(No text returned)";

    // Populate result table
    resultTableBody.innerHTML = "";
    const items = data.items || [];

    if (items.length === 0) {
      const emptyRow = document.createElement("tr");
      emptyRow.innerHTML = `<td colspan="6" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">No items detected in document.</td>`;
      resultTableBody.appendChild(emptyRow);
    } else {
      items.forEach((item) => {
        const row = document.createElement("tr");

        let badgeClass = "status-matched";
        let statusIcon = "✓";
        if (item.status_category === "review") {
          badgeClass = "status-review";
          statusIcon = "⚡";
        } else if (item.status_category === "verify" || item.status_category === "suggested") {
          badgeClass = "status-verify";
          statusIcon = "🔍";
        } else if (item.status_category === "uncataloged" || item.status_category === "unidentified") {
          badgeClass = "status-unidentified";
          statusIcon = "✦";
        }

        // 1. Catalog Product formatting: specific product name + category & SKU badge
        const isCat = Boolean(item.is_catalog_item && item.product_id);
        const skuBadge = isCat
          ? `<span class="product-sku"><span class="sku-id">${escapeHtml(item.product_id)}</span>${item.category ? ' • <span class="sku-cat">' + escapeHtml(item.category) + '</span>' : ''}</span>`
          : `<span class="product-sku new-item-sku">✦ Uncataloged Item</span>`;

        // 2. Unit Categorization formatting
        const unitVal = item.unit_display || item.unit || "-";
        const unitCat = item.unit_category || (item.unit ? "general" : "none");
        const unitBadge = unitVal !== "-"
          ? `<span class="unit-badge unit-cat-${escapeHtml(unitCat)}">${escapeHtml(unitVal)}</span>`
          : `<span class="unit-badge unit-cat-none">-</span>`;

        // 3. Confidence meter formatting with visual bar and tiers
        let confHtml = "";
        if (isCat) {
          const confPct = item.confidence_percent || "100%";
          const numVal = Math.min(100, Math.max(0, Math.round((item.confidence || 1.0) * 100)));
          let tierLabel = "High";
          let tierClass = "conf-tier-high";
          if (numVal < 60) {
            tierLabel = "Review";
            tierClass = "conf-tier-low";
          } else if (numVal < 80) {
            tierLabel = "Good";
            tierClass = "conf-tier-med";
          }
          confHtml = `
            <div class="conf-cell">
              <div class="conf-top">
                <span class="conf-percent ${tierClass}">${escapeHtml(confPct)}</span>
                <span class="conf-tier-pill ${tierClass}">${tierLabel}</span>
              </div>
              <div class="conf-bar-track" title="Match Score: ${numVal}%">
                <div class="conf-bar-fill ${tierClass}" style="width: ${numVal}%;"></div>
              </div>
            </div>
          `;
        } else {
          confHtml = `
            <div class="conf-cell conf-custom-cell">
              <span class="conf-tier-pill conf-tier-custom">✦ Uncataloged</span>
              <span class="conf-custom-sub">Clean Text Extracted</span>
            </div>
          `;
        }

        row.innerHTML = `
          <td><span class="raw-item-text">${escapeHtml(item.raw_text || "")}</span></td>
          <td>
            <span class="product-name ${isCat ? 'cat-matched-name' : 'custom-product-name'}">${escapeHtml(item.product || item.product_text || "Custom Item")}</span>
            ${skuBadge}
          </td>
          <td class="qty-cell">${item.quantity !== undefined && item.quantity !== null && item.quantity !== 0 ? item.quantity : "-"}</td>
          <td>${unitBadge}</td>
          <td>${confHtml}</td>
          <td>
            <span class="status-badge ${badgeClass}">
              <span class="status-icon">${statusIcon}</span>
              ${escapeHtml(item.display_status || item.status || "Unknown")}
            </span>
          </td>
        `;
        resultTableBody.appendChild(row);
      });
    }

    resultsSection.classList.remove("hidden");
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Loading States
  function setTextLoading(isLoading) {
    if (isLoading) {
      submitTextBtn.setAttribute("disabled", "true");
      btnTextSpinner.classList.remove("hidden");
      submitTextLabel.textContent = "Processing...";
    } else {
      submitTextBtn.removeAttribute("disabled");
      btnTextSpinner.classList.add("hidden");
      submitTextLabel.textContent = "Match Shopping List";
    }
  }

  function setFileLoading(isLoading) {
    if (isLoading) {
      submitBtn.setAttribute("disabled", "true");
      btnSpinner.classList.remove("hidden");
      btnText.textContent = "Processing with Cloud Vision...";
    } else {
      if (activeFile) submitBtn.removeAttribute("disabled");
      btnSpinner.classList.add("hidden");
      btnText.textContent = "Scan with Cloud Vision & Match";
    }
  }

  function showError(code, message) {
    errorCode.textContent = code;
    if (code === "API_KEY_REQUIRED") {
      errorMessage.innerHTML = `${escapeHtml(message)} <br><button type="button" class="btn-sm btn-outline" style="margin-top:0.6rem; color:#38bdf8; border-color:#38bdf8; font-weight:600;" onclick="document.getElementById('tabDirectText').click()">✍️ Switch to Direct Text Input (Instant Matching)</button>`;
    } else {
      errorMessage.textContent = message;
    }
    errorAlert.classList.remove("hidden");
    errorAlert.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function hideError() {
    errorAlert.classList.add("hidden");
  }

  // Catalog Functions
  async function loadCatalog() {
    try {
      const res = await fetch("/api/catalog");
      const data = await res.json();
      if (data.success && Array.isArray(data.products)) {
        catalogProducts = data.products;
        renderCatalogGrid(catalogProducts);
        if (toggleCatalogBtn) {
          toggleCatalogBtn.textContent = `📋 View Catalog (${catalogProducts.length} Items)`;
        }
      }
    } catch (e) {
      console.warn("Failed to load catalog:", e);
    }
  }

  function renderCatalogGrid(products) {
    if (!catalogGrid) return;
    catalogGrid.innerHTML = "";
    if (products.length === 0) {
      catalogGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 1rem;">No matching catalog items found.</div>`;
      return;
    }
    products.forEach((p) => {
      const card = document.createElement("div");
      card.className = "catalog-item-card";
      card.title = "Click to add to shopping list";
      const guName = p.aliases_gu ? p.aliases_gu.split("|")[0] : "";
      const hiName = p.aliases_hi ? p.aliases_hi.split("|")[0] : "";
      const aliasStr = [guName, hiName].filter(Boolean).join(" • ");
      card.innerHTML = `
        <div class="catalog-item-name">${escapeHtml(p.canonical_name)}</div>
        ${aliasStr ? `<div class="catalog-item-aliases">${escapeHtml(aliasStr)}</div>` : ""}
        <div class="catalog-item-sku">${escapeHtml(p.product_id)} • ${escapeHtml(p.category || "grocery")}</div>
      `;
      card.addEventListener("click", () => {
        const text = shoppingListText.value.trim();
        const addition = p.canonical_name;
        shoppingListText.value = text ? `${text}\n${addition}` : addition;
        shoppingListText.focus();
      });
      catalogGrid.appendChild(card);
    });
  }

  if (toggleCatalogBtn) {
    toggleCatalogBtn.addEventListener("click", () => {
      if (!catalogModal) return;
      const isHidden = catalogModal.classList.contains("hidden");
      if (isHidden) {
        catalogModal.classList.remove("hidden");
        if (catalogProducts.length === 0) loadCatalog();
        if (catalogSearchInput) catalogSearchInput.focus();
      } else {
        catalogModal.classList.add("hidden");
      }
    });
  }

  if (closeCatalogBtn) {
    closeCatalogBtn.addEventListener("click", () => {
      if (catalogModal) catalogModal.classList.add("hidden");
    });
  }

  if (catalogSearchInput) {
    catalogSearchInput.addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase().trim();
      if (!query) {
        renderCatalogGrid(catalogProducts);
      } else {
        const filtered = catalogProducts.filter((p) => {
          return (
            (p.canonical_name && p.canonical_name.toLowerCase().includes(query)) ||
            (p.aliases_en && p.aliases_en.toLowerCase().includes(query)) ||
            (p.aliases_gu && p.aliases_gu.toLowerCase().includes(query)) ||
            (p.aliases_hi && p.aliases_hi.toLowerCase().includes(query)) ||
            (p.product_id && p.product_id.toLowerCase().includes(query)) ||
            (p.category && p.category.toLowerCase().includes(query))
          );
        });
        renderCatalogGrid(filtered);
      }
    });
  }

  // Pre-load catalog on initialization
  loadCatalog();

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});

