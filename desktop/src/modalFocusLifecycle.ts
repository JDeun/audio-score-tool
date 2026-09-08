const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true",
  );
}

export function installModalFocusLifecycle() {
  let activeDialog: HTMLElement | null = null;
  let returnFocus: HTMLElement | null = null;
  let focusFrame: number | null = null;

  const restoreFocus = () => {
    if (focusFrame !== null) {
      window.cancelAnimationFrame(focusFrame);
      focusFrame = null;
    }
    const target = returnFocus;
    returnFocus = null;
    if (target?.isConnected) {
      window.requestAnimationFrame(() => target.focus());
    }
  };

  const syncDialog = () => {
    const dialogs = Array.from(
      document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'),
    ).filter((dialog) => !dialog.classList.contains("onboarding-card"));
    const nextDialog = dialogs.at(-1) ?? null;
    if (nextDialog === activeDialog) return;

    if (activeDialog && !activeDialog.isConnected) restoreFocus();
    activeDialog = nextDialog;
    if (!activeDialog) return;

    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    focusFrame = window.requestAnimationFrame(() => {
      const focusables = focusableElements(activeDialog!);
      (focusables[0] ?? activeDialog)?.focus();
      focusFrame = null;
    });
  };

  const onKeyDown = (event: KeyboardEvent) => {
    const dialog = activeDialog;
    if (!dialog?.isConnected) return;

    if (event.key === "Escape") {
      const dismiss = dialog.querySelector<HTMLButtonElement>(
        "[data-dialog-dismiss], .confirm-actions .secondary-button",
      );
      if (dismiss) {
        event.preventDefault();
        dismiss.click();
      }
      return;
    }

    if (event.key !== "Tab") return;
    const focusables = focusableElements(dialog);
    if (focusables.length === 0) {
      event.preventDefault();
      dialog.tabIndex = -1;
      dialog.focus();
      return;
    }

    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const current = document.activeElement;
    if (event.shiftKey && (current === first || !dialog.contains(current))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && current === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const observer = new MutationObserver(syncDialog);
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("keydown", onKeyDown);
  syncDialog();

  return () => {
    observer.disconnect();
    document.removeEventListener("keydown", onKeyDown);
    restoreFocus();
  };
}
