/**
 * Waar komt dit vandaan, en staat het hier?
 *
 * Drie toestanden die uit elkaar gehouden moeten worden:
 *
 * * **eigen bestand** — uit je NAS-mappen. Geen badge: dat is het normale
 *   geval en een badge op alles is geen badge.
 * * **opgehaald** — van een bron, staat nu lokaal. Bij een tijdelijke
 *   (readahead-)download erbij tot wanneer.
 * * **online** — van een bron, nog niet opgehaald.
 */

export function SourceBadge({
  fromSource,
  hasFile,
  expiresAt,
  className = "",
}: {
  fromSource: boolean;
  hasFile: boolean;
  expiresAt?: string | null;
  className?: string;
}) {
  if (!fromSource) return null;

  if (!hasFile) {
    return (
      <Badge className={`bg-ink-900/80 text-slate-300 ${className}`} title="Nog niet opgehaald">
        ☁ online
      </Badge>
    );
  }

  if (expiresAt) {
    const days = Math.max(0, Math.ceil((Date.parse(expiresAt) - Date.now()) / 86_400_000));
    return (
      <Badge
        className={`bg-ink-900/80 text-warning ${className}`}
        title={`Tijdelijk opgehaald; wordt over ${days} dagen weer opgeruimd`}
      >
        ⏳ {days}d
      </Badge>
    );
  }

  return (
    <Badge className={`bg-ink-900/80 text-accent ${className}`} title="Opgehaald van een bron">
      ✓ lokaal
    </Badge>
  );
}

/** De serie-kaart wil alleen weten of het een abonnement is. */
export function SubscriptionBadge({ fromSource }: { fromSource: boolean }) {
  if (!fromSource) return null;
  return (
    <Badge className="bg-ink-900/80 text-slate-300" title="Gevolgd bij een bron">
      ☁ abonnement
    </Badge>
  );
}

function Badge({
  children,
  className,
  title,
}: {
  children: React.ReactNode;
  className: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`pointer-events-none rounded px-1.5 py-0.5 text-[10px] font-medium ${className}`}
    >
      {children}
    </span>
  );
}
