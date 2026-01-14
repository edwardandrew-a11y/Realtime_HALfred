★ Insight ─────────────────────────────────────
  Agents vs Skills in Claude Code:
  - Agents: Autonomous subprocesses launched with the Task tool for complex multi-step work (research, review, design)
  - Skills: Invoked with the Skill tool, they provide specialized prompts/workflows (often user-initiated with /command)
  ─────────────────────────────────────────────────

  Quick Reference Guide

  🔍 Research & Analysis (I use these proactively)

  - best-practices-researcher - External docs, community standards, industry best practices
  - framework-docs-researcher - Deep dive into library/framework documentation
  - repo-research-analyst - Analyze repository structure, conventions, patterns
  - git-history-analyzer - Understand code evolution, trace origins, identify key contributors
  - pattern-recognition-specialist - Find design patterns, anti-patterns, code smells

  🏗️ Architecture & Design (I use when planning features)

  - architecture-strategist - Evaluate architectural decisions, system design
  - backend-architect - Scalable API design, microservices, distributed systems
  - saga-orchestration (skill) - Distributed transactions, cross-aggregate workflows
  - microservices-patterns (skill) - Service boundaries, event-driven communication
  - cqrs-implementation (skill) - Command/query separation patterns

  ✅ Code Review (I use after writing code)

  - kieran-{rails|typescript|python}-reviewer - Language-specific quality reviews with high standards
  - dhh-rails-reviewer - Rails conventions, anti-JavaScript-framework patterns
  - security-sentinel - Security audits, vulnerability scanning, OWASP compliance
  - performance-oracle - Performance bottlenecks, optimization, scalability
  - code-simplicity-reviewer - Ensure minimal, YAGNI-compliant code
  - data-integrity-guardian - Database migration safety, referential integrity
  - data-migration-expert - ID mappings, rollback safety, data transformations

  🎨 Design & Frontend

  - design-iterator - Iterative design refinement (5-10x iterations)
  - figma-design-sync - Sync implementation with Figma designs
  - design-implementation-reviewer - Verify UI matches Figma specs

  🐛 Bug Fixing & Deployment

  - bug-reproduction-validator - Verify if reported behavior is actually a bug
  - deployment-verification-agent - Pre/post-deploy checklists, rollback procedures
  - pr-comment-resolver - Address PR comments systematically

  📝 Workflows (You invoke these with /command)

  - /workflows:plan - Transform features into structured plans
  - /workflows:work - Execute plans efficiently
  - /workflows:review - Exhaustive multi-agent code reviews
  - /workflows:compound - Document solved problems for team knowledge

  🔧 Specialized

  - agent-native-architecture (skill) - Build AI agents with prompt-native architecture
  - dspy-ruby (skill) - Type-safe LLM applications in Ruby
  - temporal-python-testing (skill) - Temporal workflow testing strategies

  How It Works

  I use agents proactively based on your task:
  - Building a feature → I'll launch architecture-strategist or backend-architect
  - After coding → I'll launch kieran-python-reviewer or security-sentinel
  - Bug report → I'll launch bug-reproduction-validator
  - Performance issues → I'll launch performance-oracle

  You invoke skills explicitly when needed:
  /workflows:plan        # Create structured plan
  /saga-orchestration    # Learn saga patterns
  /code-review:code-review  # Deep code review

  The system is designed so I automatically choose the right agents for your work, while you can manually invoke skills when you want specific expertise or workflows. 