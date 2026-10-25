import { create } from 'zustand'

import type { CopilotTranslateResponseKind } from '@/shared/api/generated/model'

type ViewMode = 'standard' | 'focus'
type ActiveTab = 'config' | 'blocks' | 'data' | 'ai' | 'pills' | 'copilot'
type ContextType = 'informe' | 'flujo'

interface FocusContext {
  type: ContextType
  entityId: string
}

// #277 — lo que el copiloto propone lo declara el servidor en su respuesta.
export type CopilotActionKind = CopilotTranslateResponseKind

export interface CopilotAction {
  kind: CopilotActionKind
  payload: unknown
}

interface FocusState {
  viewMode: ViewMode
  drawerVisible: boolean
  activeTab: ActiveTab
  context: FocusContext | null
  pendingAction: CopilotAction | null
  setViewMode: (mode: ViewMode) => void
  toggleDrawer: () => void
  setActiveTab: (tab: ActiveTab) => void
  setContext: (ctx: FocusContext) => void
  dispatchCopilotAction: (action: CopilotAction) => void
  clearPendingAction: () => void
  reset: () => void
}

const INITIAL_STATE = {
  viewMode: 'standard' as ViewMode,
  drawerVisible: false,
  activeTab: 'blocks' as ActiveTab,
  context: null,
  pendingAction: null,
}

export const useFocusStore = create<FocusState>((set) => ({
  ...INITIAL_STATE,
  setViewMode: (mode) => set({ viewMode: mode }),
  toggleDrawer: () => set((s) => ({ drawerVisible: !s.drawerVisible })),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setContext: (ctx) => set({ context: ctx }),
  dispatchCopilotAction: (action) => set({ pendingAction: action }),
  clearPendingAction: () => set({ pendingAction: null }),
  reset: () => set(INITIAL_STATE),
}))
