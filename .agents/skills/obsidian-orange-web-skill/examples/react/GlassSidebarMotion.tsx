/**
 * Original Obsidian Orange recipe: React + Motion for dynamic navigation.
 * Install: npm i motion
 * Import ./GlassSidebarMotion.css and adapt routing, icons and branding to your app.
 * Official docs: https://motion.dev/docs/react-layout-animations
 *                https://motion.dev/docs/react-animate-presence
 *                https://motion.dev/docs/react-use-reduced-motion
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AnimatePresence,
  LayoutGroup,
  motion,
  useReducedMotion,
} from "motion/react";
import "./GlassSidebarMotion.css";

export type NavEntry = {
  href: string;
  label: string;
  icon: ReactNode;
  /** Optional: a true section route may own nested pages. */
  matches?: (currentPath: string) => boolean;
  permitted?: boolean;
};

type Props = {
  brand: string;
  brandMark: ReactNode;
  links: NavEntry[];
  currentPath: string;
  children: ReactNode;
  footer?: ReactNode;
};

const PREFERENCE_KEY = "obsidian-orange-sidebar-mode";

function SidebarLinks({
  compact, mobile = false, entries, currentPath, reduceMotion, onMobileNavigate
}: {
  compact: boolean; mobile?: boolean; entries: NavEntry[]; currentPath: string;
  reduceMotion: boolean | null; onMobileNavigate?: () => void;
}) {
  const active = (item: NavEntry) => item.matches ? item.matches(currentPath) : currentPath === item.href;
  const transition = reduceMotion ? { duration: 0 } : { type: "spring" as const, stiffness: 440, damping: 39 };
  return (
      <nav className="oo-fusion-links" aria-label={mobile ? "Mobile primary" : "Primary"}>
        {entries.map(item => {
          const selected = active(item);
          return (
            <a
              key={item.href}
              href={item.href}
              className={`oo-fusion-link ${selected ? "is-current" : ""}`}
              aria-current={selected ? "page" : undefined}
              aria-label={compact ? item.label : undefined}
              data-tooltip={compact ? item.label : undefined}
              title={compact ? item.label : undefined}
              onClick={mobile ? onMobileNavigate : undefined}
            >
              {selected && !mobile && (
                <motion.span
                  layoutId="oo-fusion-nav-active"
                  className="oo-fusion-active"
                  transition={transition}
                  aria-hidden="true"
                />
              )}
              <span className="oo-fusion-icon" aria-hidden="true">{item.icon}</span>
              <AnimatePresence initial={false} mode="popLayout">
                {!compact && (
                  <motion.span
                    key="label"
                    className="oo-fusion-label"
                    initial={reduceMotion ? false : { opacity: 0, x: -5 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -5 }}
                    transition={{ duration: reduceMotion ? 0 : 0.14 }}
                  >{item.label}</motion.span>
                )}
              </AnimatePresence>
            </a>
          );
        })}
      </nav>
  );
}

export function GlassSidebarMotion({
  brand,
  brandMark,
  links,
  currentPath,
  children,
  footer,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const reduceMotion = useReducedMotion();

  // Client-only: avoids SSR mismatches; no localStorage reference during render.
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(PREFERENCE_KEY) === "collapsed");
    } catch { /* Privacy settings may block storage. */ }
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (mobileOpen && !dialog.open) dialog.showModal();
    if (!mobileOpen && dialog.open) dialog.close();
  }, [mobileOpen]);

  // Real route changes always dismiss the mobile drawer.
  useEffect(() => { setMobileOpen(false); }, [currentPath]);

  function toggleCollapsed() {
    setCollapsed(prev => {
      const next = !prev;
      try { localStorage.setItem(PREFERENCE_KEY, next ? "collapsed" : "expanded"); }
      catch { /* UI still works if persistence fails. */ }
      return next;
    });
  }

  const entries = links.filter(item => item.permitted !== false);

  return (
    <div className={`oo-fusion ${collapsed ? "is-collapsed" : "is-expanded"}`}>
      <div className="oo-fusion-shell">
        <aside className="oo-fusion-sidebar" aria-label="Application side menu">
          <div className="oo-fusion-brand-row">
            <span className="oo-fusion-mark" aria-hidden="true">{brandMark}</span>
            <AnimatePresence initial={false}>
              {!collapsed && (
                <motion.span
                  key="brand"
                  className="oo-fusion-brand"
                  initial={reduceMotion ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: reduceMotion ? 0 : 0.12 }}
                >{brand}</motion.span>
              )}
            </AnimatePresence>
            <button
              type="button"
              className="oo-fusion-toggle"
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-controls="oo-fusion-main-nav"
              aria-expanded={!collapsed}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >{collapsed ? "»" : "«"}</button>
          </div>
          <LayoutGroup id="oo-fusion-desktop-nav">
            <div id="oo-fusion-main-nav" className="oo-fusion-navigation">
              <SidebarLinks compact={collapsed} entries={entries} currentPath={currentPath}
                reduceMotion={reduceMotion} />
            </div>
          </LayoutGroup>
          {footer && <div className="oo-fusion-footer">{footer}</div>}
        </aside>

        <main id="main-content" className="oo-fusion-main">
          <div className="oo-fusion-mobile-utility">
            <button type="button" className="oo-fusion-mobile-open"
              onClick={() => setMobileOpen(true)} aria-haspopup="dialog"
              aria-label="Open navigation">☰ <span>Menu</span></button>
            <span className="oo-fusion-mobile-title">{brand}</span>
          </div>
          {children}
        </main>
      </div>
      {/* Native modal dialog handles focus trapping, Escape and focus restoration. */}
      <dialog
        ref={dialogRef}
        className="oo-fusion-dialog"
        aria-label="Mobile navigation"
        onClose={() => setMobileOpen(false)}
        onClick={event => {
          if (event.currentTarget === event.target) event.currentTarget.close();
        }}
      >
        <div className="oo-fusion-dialog-sheet">
          <div className="oo-fusion-brand-row">
            <span className="oo-fusion-mark" aria-hidden="true">{brandMark}</span>
            <strong className="oo-fusion-brand">{brand}</strong>
            <button type="button" className="oo-fusion-toggle"
              aria-label="Close navigation" onClick={() => dialogRef.current?.close()}>×</button>
          </div>
          <SidebarLinks compact={false} mobile entries={entries} currentPath={currentPath}
            reduceMotion={reduceMotion} onMobileNavigate={() => dialogRef.current?.close()} />
          {footer && <div className="oo-fusion-footer">{footer}</div>}
        </div>
      </dialog>
    </div>
  );
}
