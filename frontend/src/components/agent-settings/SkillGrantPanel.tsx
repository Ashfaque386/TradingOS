"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gated } from "@/components/ui/gated";

/** spec 002 US8: view/grant/revoke this agent's real `AgentSkillMap` rows -- the backend
 * catalog + CRUD API already existed (`src/api/routers/skills.py`); this is the first frontend
 * surface for it, and `SkillRegistry.execute()` now genuinely enforces these grants at call
 * time (previously recorded but inert). `agentName` should be the real `KNOWN_AGENTS` name
 * (e.g. "market_analyst"), not necessarily the prompt-registry slug this settings page is keyed
 * by -- the caller resolves that once via the real Agent Registry (see the settings page). */
export function SkillGrantPanel({ agentName }: { agentName: string }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<string>("");

  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: api.skills });
  const grantsQuery = useQuery({ queryKey: ["agent-skill-map"], queryFn: api.agentSkillMap });

  const grantsForAgent = useMemo(
    () => (grantsQuery.data ?? []).filter((g) => g.agent_name === agentName),
    [grantsQuery.data, agentName],
  );
  const grantedSkillNames = useMemo(
    () => new Set(grantsForAgent.map((g) => g.skill_name)),
    [grantsForAgent],
  );
  const ungrantedSkills = useMemo(
    () => (skillsQuery.data ?? []).filter((s) => !grantedSkillNames.has(s.name)),
    [skillsQuery.data, grantedSkillNames],
  );

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["agent-skill-map"] });

  const grant = useMutation({
    mutationFn: (skillName: string) => api.grantSkillToAgent(agentName, skillName),
    onSuccess: () => {
      setError(null);
      setSelectedSkill("");
      invalidate();
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "grant failed"),
  });
  const revoke = useMutation({
    mutationFn: (grantId: string) => api.revokeSkillGrant(grantId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "revoke failed"),
  });

  const isLoading = skillsQuery.isLoading || grantsQuery.isLoading;

  return (
    <Card eyebrow="Tools / Skills" title="Skill grants" density="dense">
      {isLoading ? (
        <div className="h-16 animate-pulse rounded-card bg-bg" />
      ) : grantsForAgent.length === 0 ? (
        <p className="text-[11px] italic text-text-faint">No skills granted to this agent.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {grantsForAgent.map((g) => (
            <li
              key={g.id}
              className="flex items-center gap-2 rounded-lg border border-card-edge p-2 text-xs"
            >
              <Badge variant="outline">{g.skill_name}</Badge>
              <span className="text-text-faint">
                granted {new Date(g.granted_at).toLocaleDateString()}
              </span>
              <Gated permission="manageAgentConfig">
                <button
                  className="ml-auto rounded-md border border-card-edge px-1.5 py-0.5 text-[11px] text-destructive disabled:opacity-50"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(g.id)}
                >
                  Revoke
                </button>
              </Gated>
            </li>
          ))}
        </ul>
      )}

      <Gated permission="manageAgentConfig">
        <div className="mt-3 flex items-center gap-2">
          <select
            className="flex-1 rounded-md border border-card-edge bg-bg px-1.5 py-1 text-[11px]"
            value={selectedSkill}
            onChange={(e) => setSelectedSkill(e.target.value)}
          >
            <option value="">Grant a skill…</option>
            {ungrantedSkills.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
          <button
            className="rounded-md bg-primary px-2 py-1 text-[11px] text-primary-foreground disabled:opacity-50"
            disabled={!selectedSkill || grant.isPending}
            onClick={() => grant.mutate(selectedSkill)}
          >
            Grant
          </button>
        </div>
      </Gated>

      {error && <p className="mt-2 text-[11px] text-destructive">{error}</p>}
    </Card>
  );
}
