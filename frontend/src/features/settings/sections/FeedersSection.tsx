import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  applyFeedersExample,
  buildFeedersPatch,
  draftFromConfig,
  isSectionDirty,
  pickFeeders,
} from "@/features/settings/lib/draft";
import {
  fieldErrorsFrom,
  fieldMessage,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import {
  emptyFeederEntryDraft,
  emptyLocalPageDraft,
  FEEDER_KIND_LABELS,
  FEEDER_KINDS,
  feederKindFields,
} from "@/features/settings/lib/feederKinds";
import {
  FEEDERS_POLL_INTERVAL_MAX_S,
  FEEDERS_POLL_INTERVAL_MIN_S,
  feederEntryHasError,
  localPageHasError,
  validateDockerSocketPath,
  validateFeederEntry,
  validateFeedersPollInterval,
  validateLocalPage,
} from "@/features/settings/lib/validation";
import type {
  FeederEntryDraft,
  LocalPageDraft,
} from "@/features/settings/types";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FeederKind, FlightSiteConfig } from "@/lib/api/config";

export interface FeedersSectionProps {
  config: FlightSiteConfig;
  /** `secrets_set`, unfiltered — this section reads out every
   * `feeders.stats_urls.<name>` key itself rather than the caller
   * pre-filtering, since the set of names is exactly the entries this
   * section's own draft owns. */
  secretsSet: Record<string, boolean>;
}

const INPUT_CLASS =
  "flex h-8 w-full min-w-0 rounded-md border border-input bg-transparent px-2 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

/**
 * Every network this receiver feeds, plus the locally hosted pages beside
 * it (roadmap slice 077, `docs/design/077-feeders-page.md`).
 *
 * Applies on save with no restart badge, for the same reason Enrichment has
 * none: `service.apply_settings()` rebuilds the feeder set's probes from
 * whatever was just saved, rather than a running poll loop being started
 * once at process start and left alone.
 *
 * The per-entry stats URL follows the AeroDataBox key's masked-secret
 * pattern once per row (see `FeederEntryDraft`'s doc comment) rather than
 * once for the section, because each row is its own secret keyed by the
 * entry's `name` (`secrets_set["feeders.stats_urls.<name>"]`).
 */
export function FeedersSection({ config, secretsSet }: FeedersSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickFeeders(draftFromConfig(config, secretsSet)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);

  const pollInterval = fieldMessage(
    validateFeedersPollInterval(draft.pollIntervalS),
    fieldErrors["feeders.poll_interval_s"],
  );
  const dockerSocket = fieldMessage(
    validateDockerSocketPath(draft.dockerSocket),
    fieldErrors["feeders.docker_socket"],
  );

  const entryErrors = draft.entries.map((entry) =>
    validateFeederEntry(entry, draft.entries),
  );
  const localPageErrors = draft.localPages.map((page) =>
    validateLocalPage(page),
  );

  const hasBlockingError =
    pollInterval.blocking ||
    dockerSocket.blocking ||
    entryErrors.some((errors) => feederEntryHasError(errors)) ||
    localPageErrors.some((errors) => localPageHasError(errors));

  function updateEntry(index: number, patch: Partial<FeederEntryDraft>) {
    setDraft({
      ...draft,
      entries: draft.entries.map((entry, i) =>
        i === index ? { ...entry, ...patch } : entry,
      ),
    });
  }

  function removeEntry(index: number) {
    setDraft({
      ...draft,
      entries: draft.entries.filter((_, i) => i !== index),
    });
  }

  function moveEntry(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= draft.entries.length) {
      return;
    }
    const entries = [...draft.entries];
    const [moved] = entries.splice(index, 1);
    if (moved === undefined) {
      return;
    }
    entries.splice(target, 0, moved);
    setDraft({ ...draft, entries });
  }

  function addEntry() {
    setDraft({
      ...draft,
      entries: [...draft.entries, emptyFeederEntryDraft()],
    });
  }

  function updateLocalPage(index: number, patch: Partial<LocalPageDraft>) {
    setDraft({
      ...draft,
      localPages: draft.localPages.map((page, i) =>
        i === index ? { ...page, ...patch } : page,
      ),
    });
  }

  function removeLocalPage(index: number) {
    setDraft({
      ...draft,
      localPages: draft.localPages.filter((_, i) => i !== index),
    });
  }

  function addLocalPage() {
    setDraft({
      ...draft,
      localPages: [...draft.localPages, emptyLocalPageDraft()],
    });
  }

  function handleLoadExample() {
    setDraft(applyFeedersExample(draft));
  }

  function handleSave() {
    mutation.mutate(buildFeedersPatch(draft), {
      onSuccess: (response) => {
        const next = pickFeeders(
          draftFromConfig(response.config, response.secrets_set),
        );
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-feeders"
      title="Feeders"
      description="Every network this receiver feeds, gaps in feeding, and links to the pages hosted alongside FlightSite."
    >
      <div className="flex max-w-lg flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-feeders-poll-interval">
            Poll interval (seconds)
          </Label>
          <Input
            id="settings-feeders-poll-interval"
            inputMode="numeric"
            value={draft.pollIntervalS}
            aria-invalid={pollInterval.message !== null}
            aria-describedby="settings-feeders-poll-interval-error"
            onChange={(event) => {
              setDraft({ ...draft, pollIntervalS: event.target.value });
            }}
          />
          <p className="text-xs text-muted-foreground">
            How often each feeder is probed, {FEEDERS_POLL_INTERVAL_MIN_S}–
            {FEEDERS_POLL_INTERVAL_MAX_S} seconds.
          </p>
          <FieldError
            id="settings-feeders-poll-interval-error"
            message={pollInterval.message}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-feeders-docker-socket">
            Docker socket path
          </Label>
          <Input
            id="settings-feeders-docker-socket"
            value={draft.dockerSocket}
            placeholder="/var/run/docker.sock"
            aria-invalid={dockerSocket.message !== null}
            aria-describedby="settings-feeders-docker-socket-error"
            onChange={(event) => {
              setDraft({ ...draft, dockerSocket: event.target.value });
            }}
          />
          <p className="text-xs text-muted-foreground">
            Lets FlightSite read feeder container logs and health. Requires the
            socket mounted into the backend container — see INSTALL. Leave blank
            to disable (socket-only signals then read &quot;unknown&quot;, never
            &quot;down&quot;).
          </p>
          <FieldError
            id="settings-feeders-docker-socket-error"
            message={dockerSocket.message}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Feeder entries</h3>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleLoadExample}
            >
              Load the example for a Pi with ultrafeeder + piaware + fr24 +
              opensky
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addEntry}
            >
              <Plus className="size-4" aria-hidden="true" />
              Add feeder
            </Button>
          </div>
        </div>

        {draft.entries.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No feeders configured yet.
          </p>
        )}

        {draft.entries.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50 text-left text-xs font-medium text-muted-foreground">
                  <th scope="col" className="p-2">
                    Name
                  </th>
                  <th scope="col" className="p-2">
                    Label
                  </th>
                  <th scope="col" className="p-2">
                    Kind
                  </th>
                  <th scope="col" className="p-2">
                    Details
                  </th>
                  <th scope="col" className="p-2">
                    Open link (web_url)
                  </th>
                  <th scope="col" className="p-2">
                    Stats URL
                  </th>
                  <th scope="col" className="p-2">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {draft.entries.map((entry, index) => {
                  const errors = entryErrors[index];
                  const fields = feederKindFields(entry.kind);
                  const serverPath = (field: string) =>
                    fieldErrors[`feeders.entries.${index}.${field}`];
                  const nameField = fieldMessage(
                    errors?.name ?? null,
                    serverPath("name"),
                  );
                  const labelField = fieldMessage(
                    errors?.label ?? null,
                    serverPath("label"),
                  );
                  const urlField = fieldMessage(
                    errors?.url ?? null,
                    serverPath("url"),
                  );
                  const containerField = fieldMessage(
                    errors?.container ?? null,
                    serverPath("container"),
                  );
                  const hostField = fieldMessage(
                    errors?.host ?? null,
                    serverPath("host"),
                  );
                  const mlatField = fieldMessage(
                    errors?.mlatPort ?? null,
                    serverPath("mlat_port"),
                  );
                  const beastField = fieldMessage(
                    errors?.beastPort ?? null,
                    serverPath("beast_port"),
                  );
                  const webUrlField = fieldMessage(
                    errors?.webUrl ?? null,
                    serverPath("web_url"),
                  );
                  const statsUrlServerError =
                    fieldErrors[`feeders.stats_urls.${entry.name.trim()}`] ??
                    null;

                  return (
                    <tr
                      key={index}
                      data-testid="feeders-entry-row"
                      className="border-b border-border align-top last:border-0"
                    >
                      <td className="p-2">
                        <Input
                          aria-label={`Feeder ${index + 1} name`}
                          className={INPUT_CLASS}
                          value={entry.name}
                          aria-invalid={nameField.message !== null}
                          onChange={(event) => {
                            updateEntry(index, { name: event.target.value });
                          }}
                        />
                        <FieldError
                          id={`feeders-entry-${index}-name-error`}
                          message={nameField.message}
                        />
                      </td>
                      <td className="p-2">
                        <Input
                          aria-label={`Feeder ${index + 1} label`}
                          className={INPUT_CLASS}
                          value={entry.label}
                          aria-invalid={labelField.message !== null}
                          onChange={(event) => {
                            updateEntry(index, { label: event.target.value });
                          }}
                        />
                        <FieldError
                          id={`feeders-entry-${index}-label-error`}
                          message={labelField.message}
                        />
                      </td>
                      <td className="p-2">
                        <select
                          aria-label={`Feeder ${index + 1} kind`}
                          value={entry.kind}
                          onChange={(event) => {
                            updateEntry(index, {
                              kind: event.target.value as FeederKind,
                            });
                          }}
                          className={INPUT_CLASS}
                        >
                          {FEEDER_KINDS.map((kind) => (
                            <option key={kind} value={kind}>
                              {FEEDER_KIND_LABELS[kind]}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="p-2">
                        <div className="flex flex-col gap-1">
                          {fields.url && (
                            <div>
                              <Input
                                aria-label={`Feeder ${index + 1} URL`}
                                className={INPUT_CLASS}
                                placeholder="http://host.docker.internal:8080/"
                                value={entry.url}
                                aria-invalid={urlField.message !== null}
                                onChange={(event) => {
                                  updateEntry(index, {
                                    url: event.target.value,
                                  });
                                }}
                              />
                              <FieldError
                                id={`feeders-entry-${index}-url-error`}
                                message={urlField.message}
                              />
                            </div>
                          )}
                          {fields.container && (
                            <div>
                              <Input
                                aria-label={`Feeder ${index + 1} container`}
                                className={INPUT_CLASS}
                                placeholder="ultrafeeder"
                                value={entry.container}
                                aria-invalid={containerField.message !== null}
                                onChange={(event) => {
                                  updateEntry(index, {
                                    container: event.target.value,
                                  });
                                }}
                              />
                              <FieldError
                                id={`feeders-entry-${index}-container-error`}
                                message={containerField.message}
                              />
                            </div>
                          )}
                          {fields.hostPorts && (
                            <>
                              <div>
                                <Input
                                  aria-label={`Feeder ${index + 1} host`}
                                  className={INPUT_CLASS}
                                  placeholder="feed.adsbexchange.com"
                                  value={entry.host}
                                  aria-invalid={hostField.message !== null}
                                  onChange={(event) => {
                                    updateEntry(index, {
                                      host: event.target.value,
                                    });
                                  }}
                                />
                                <FieldError
                                  id={`feeders-entry-${index}-host-error`}
                                  message={hostField.message}
                                />
                              </div>
                              <div className="flex gap-1">
                                <div className="flex-1">
                                  <Input
                                    aria-label={`Feeder ${index + 1} MLAT port`}
                                    className={INPUT_CLASS}
                                    inputMode="numeric"
                                    placeholder="31090"
                                    value={entry.mlatPort}
                                    aria-invalid={mlatField.message !== null}
                                    onChange={(event) => {
                                      updateEntry(index, {
                                        mlatPort: event.target.value,
                                      });
                                    }}
                                  />
                                  <FieldError
                                    id={`feeders-entry-${index}-mlat-port-error`}
                                    message={mlatField.message}
                                  />
                                </div>
                                <div className="flex-1">
                                  <Input
                                    aria-label={`Feeder ${index + 1} Beast port`}
                                    className={INPUT_CLASS}
                                    inputMode="numeric"
                                    placeholder="30004"
                                    value={entry.beastPort}
                                    aria-invalid={beastField.message !== null}
                                    onChange={(event) => {
                                      updateEntry(index, {
                                        beastPort: event.target.value,
                                      });
                                    }}
                                  />
                                  <FieldError
                                    id={`feeders-entry-${index}-beast-port-error`}
                                    message={beastField.message}
                                  />
                                </div>
                              </div>
                            </>
                          )}
                          {!fields.url &&
                            !fields.container &&
                            !fields.hostPorts && (
                              <span className="text-xs text-muted-foreground">
                                No probe fields for this kind.
                              </span>
                            )}
                        </div>
                      </td>
                      <td className="p-2">
                        <Input
                          aria-label={`Feeder ${index + 1} open link`}
                          className={INPUT_CLASS}
                          placeholder="http://fermi.local:8080/"
                          value={entry.webUrl}
                          aria-invalid={webUrlField.message !== null}
                          onChange={(event) => {
                            updateEntry(index, { webUrl: event.target.value });
                          }}
                        />
                        <FieldError
                          id={`feeders-entry-${index}-web-url-error`}
                          message={webUrlField.message}
                        />
                      </td>
                      <td className="p-2">
                        <Input
                          type="password"
                          autoComplete="off"
                          aria-label={`Feeder ${index + 1} stats URL`}
                          className={INPUT_CLASS}
                          value={entry.statsUrlInput}
                          placeholder={
                            entry.statsUrlStored
                              ? "•••••••• (configured — leave blank to keep)"
                              : "Not configured"
                          }
                          onChange={(event) => {
                            updateEntry(index, {
                              statsUrlInput: event.target.value,
                              statsUrlTouched: true,
                            });
                          }}
                        />
                        {entry.statsUrlStored && !entry.statsUrlTouched && (
                          <div className="mt-1 flex items-center justify-between gap-1">
                            <span className="text-xs text-muted-foreground">
                              Stored.
                            </span>
                            <button
                              type="button"
                              className="text-xs font-medium text-destructive hover:underline"
                              onClick={() => {
                                updateEntry(index, {
                                  statsUrlInput: "",
                                  statsUrlTouched: true,
                                });
                              }}
                            >
                              Clear
                            </button>
                          </div>
                        )}
                        <FieldError
                          id={`feeders-entry-${index}-stats-url-error`}
                          message={statsUrlServerError}
                        />
                      </td>
                      <td className="p-2">
                        <div className="flex flex-col gap-1">
                          <button
                            type="button"
                            aria-label={`Move feeder ${index + 1} up`}
                            disabled={index === 0}
                            onClick={() => {
                              moveEntry(index, -1);
                            }}
                            className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
                          >
                            ▲
                          </button>
                          <button
                            type="button"
                            aria-label={`Move feeder ${index + 1} down`}
                            disabled={index === draft.entries.length - 1}
                            onClick={() => {
                              moveEntry(index, 1);
                            }}
                            className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
                          >
                            ▼
                          </button>
                          <button
                            type="button"
                            aria-label={`Remove feeder ${index + 1}`}
                            onClick={() => {
                              removeEntry(index);
                            }}
                            className="text-destructive hover:text-destructive/80"
                          >
                            <Trash2 className="size-4" aria-hidden="true" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Local pages</h3>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addLocalPage}
          >
            <Plus className="size-4" aria-hidden="true" />
            Add local page
          </Button>
        </div>

        {draft.localPages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No locally hosted pages linked yet.
          </p>
        )}

        {draft.localPages.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[500px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50 text-left text-xs font-medium text-muted-foreground">
                  <th scope="col" className="p-2">
                    Label
                  </th>
                  <th scope="col" className="p-2">
                    URL
                  </th>
                  <th scope="col" className="p-2">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {draft.localPages.map((page, index) => {
                  const errors = localPageErrors[index];
                  const serverPath = (field: string) =>
                    fieldErrors[`feeders.local_pages.${index}.${field}`];
                  const labelField = fieldMessage(
                    errors?.label ?? null,
                    serverPath("label"),
                  );
                  const urlField = fieldMessage(
                    errors?.url ?? null,
                    serverPath("url"),
                  );

                  return (
                    <tr
                      key={index}
                      data-testid="local-page-row"
                      className="border-b border-border align-top last:border-0"
                    >
                      <td className="p-2">
                        <Input
                          aria-label={`Local page ${index + 1} label`}
                          className={INPUT_CLASS}
                          value={page.label}
                          aria-invalid={labelField.message !== null}
                          onChange={(event) => {
                            updateLocalPage(index, {
                              label: event.target.value,
                            });
                          }}
                        />
                        <FieldError
                          id={`local-page-${index}-label-error`}
                          message={labelField.message}
                        />
                      </td>
                      <td className="p-2">
                        <Input
                          aria-label={`Local page ${index + 1} URL`}
                          className={INPUT_CLASS}
                          placeholder="http://fermi.local:8080/"
                          value={page.url}
                          aria-invalid={urlField.message !== null}
                          onChange={(event) => {
                            updateLocalPage(index, { url: event.target.value });
                          }}
                        />
                        <FieldError
                          id={`local-page-${index}-url-error`}
                          message={urlField.message}
                        />
                      </td>
                      <td className="p-2">
                        <button
                          type="button"
                          aria-label={`Remove local page ${index + 1}`}
                          onClick={() => {
                            removeLocalPage(index);
                          }}
                          className="text-destructive hover:text-destructive/80"
                        >
                          <Trash2 className="size-4" aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={hasBlockingError}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
