// Shared state shape for the SkillMD submit form. Kept in its own plain module
// (not the "use server" actions file) so both the client form and the server
// action can import it — a "use server" file may only export async functions.

export interface SubmitState {
  ok: boolean;
  error: string | null;
  createdId: string | null;
  createdName: string | null;
}

export const initialSubmitState: SubmitState = {
  ok: false,
  error: null,
  createdId: null,
  createdName: null,
};
