export function Footer() {
  return (
    <footer className="px-6 py-12 border-t border-[var(--color-border-soft)] text-[var(--color-text-faint)] text-sm">
      <div className="max-w-6xl mx-auto flex flex-wrap items-center justify-between gap-4">
        <div>© 2026 OpenGriffin contributors · Apache 2.0</div>
        <div className="flex gap-6">
          <a
            href="https://github.com/greentarallc/opengriffin"
            target="_blank"
            rel="noreferrer"
            className="hover:text-[var(--color-text-dim)] transition-colors"
          >
            GitHub
          </a>
          <a href="#features" className="hover:text-[var(--color-text-dim)] transition-colors">
            Features
          </a>
          <a href="#install" className="hover:text-[var(--color-text-dim)] transition-colors">
            Install
          </a>
          <a href="#faq" className="hover:text-[var(--color-text-dim)] transition-colors">
            FAQ
          </a>
        </div>
        <div className="text-xs">
          Not affiliated with Anthropic, OpenAI, Google, Meta, or any AI model vendor.
        </div>
      </div>
    </footer>
  );
}
