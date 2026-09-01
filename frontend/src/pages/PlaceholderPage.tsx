export interface PlaceholderPageProps {
  title: string;
  description: string;
}

/** Shared shape for a section that has no real content yet. Each of the
 * seven primary sections renders one of these until its own slice lands. */
export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <div className="flex h-full flex-col items-start justify-center gap-2 px-8">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
