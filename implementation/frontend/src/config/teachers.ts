export type TeacherId = 'astra' | 'veda' | 'nexus' | 'corel';

export interface TeacherConfig {
  id: TeacherId;
  name: string;
  subject: string;
  subjectSlug: string;
  title: string;
  tagline: string;
  avatarUrl: string;
  accentColor: string;
  personality: string;
  specialties: string[];
  greeting: string;
  defaultPath: string;
}

export const TEACHERS: Record<TeacherId, TeacherConfig> = {
  astra: {
    id: 'astra',
    name: 'Astra',
    subject: 'Data Structures & Algorithms',
    subjectSlug: 'dsa',
    title: 'Lead Algorithms & Complexity Mentor',
    tagline: 'Think in invariants. Explain the mechanism.',
    avatarUrl: '/mentor/mentor.png',
    accentColor: '#ff735c', // Coral
    personality: 'Analytical, patient, and deeply Socratic. Astra pushes you to discover invariants and reason about bounds before writing a line of code.',
    specialties: ['Sliding Window', 'Two Pointers', 'Binary Search', 'Dynamic Programming', 'Edge Cases', 'Time & Space Complexity'],
    greeting: "Before we jump into code, tell me in your own words what this problem is asking and what edge case you'd test first.",
    defaultPath: '/library',
  },
  veda: {
    id: 'veda',
    name: 'Veda',
    subject: 'Quantitative Aptitude & Logic',
    subjectSlug: 'aptitude',
    title: 'Quantitative Reasoning & Logic Coach',
    tagline: 'Spot the pattern. Reason through the numbers.',
    avatarUrl: '/mentor/veda.png',
    accentColor: '#b9e4d0', // Mint
    personality: 'Energetic, encouraging, and intuitive. Veda breaks down complex numerical problems and logical puzzles into step-by-step mental models.',
    specialties: ['Permutations & Combinations', 'Probability', 'Time & Work', 'Speed & Distance', 'Logical Deductions', 'Number Theory'],
    greeting: "Welcome! Math and reasoning aren't about memorizing formulas—they're about spotting underlying ratios and structures. Let's reason through this together.",
    defaultPath: '/learn/apt-percent',
  },
  nexus: {
    id: 'nexus',
    name: 'Nexus',
    subject: 'System Design & Distributed Systems',
    subjectSlug: 'system_design',
    title: 'Principal Systems Architect & Mentor',
    tagline: 'Map the architecture. Defend your trade-offs.',
    avatarUrl: '/mentor/nexus.png',
    accentColor: '#8c78b8', // Lavender
    personality: 'Thoughtful, architectural, and pragmatically rigorous. Nexus challenges your scaling decisions, bottleneck identification, and fault tolerance choices.',
    specialties: ['Distributed Caching', 'Rate Limiting', 'Message Queues', 'Database Sharding', 'CAP Trade-offs', 'High Availability'],
    greeting: "Every architecture is a set of compromises. Tell me: what scale are we designing for, and what happens when the primary network link partitions?",
    defaultPath: '/studio',
  },
  corel: {
    id: 'corel',
    name: 'Corel',
    subject: 'CS Fundamentals & Operating Systems',
    subjectSlug: 'cs_fundamentals',
    title: 'Computer Systems & Fundamentals Coach',
    tagline: 'From silicon to sockets. Understand the core.',
    avatarUrl: '/mentor/corel.png',
    accentColor: '#ffad9e', // Soft coral
    personality: 'Knowledgeable, lucid, and grounded in first principles. Corel connects high-level abstractions down to kernel scheduling, memory pages, and network frames.',
    specialties: ['Processes & Threads', 'CPU Scheduling', 'Virtual Memory & Paging', 'ACID & Transactions', 'TCP/IP 3-Way Handshake', 'OOP & Design Patterns'],
    greeting: "Let's peel back the layers. How does the kernel actually manage this resource when two competing threads access it concurrently?",
    defaultPath: '/learn/cs-processes',
  },
};

export const TEACHER_LIST: TeacherConfig[] = Object.values(TEACHERS);

export function getTeacherForSubject(subjectOrCollection?: string | null): TeacherConfig {
  if (!subjectOrCollection) return TEACHERS.astra;
  const s = subjectOrCollection.toLowerCase();

  if (s.includes('operating') || s.includes('os') || s.includes('dbms') || s.includes('database internals') || s.includes('network') || s.includes('fundamental') || s.includes('oop') || s.includes('computer system')) {
    return TEACHERS.corel;
  }
  if (s.includes('aptitude') || s.includes('math') || s.includes('logic') || s.includes('quantitative') || s.includes('reasoning')) {
    return TEACHERS.veda;
  }
  if (s.includes('system design') || s.includes('architecture') || s.includes('distributed') || s.includes('design studio') || s.includes('studio') || s.includes('scale')) {
    return TEACHERS.nexus;
  }
  // Default to Astra for algorithms, coding, arrays, text, etc.
  return TEACHERS.astra;
}
