import assert from "node:assert/strict"
import { test } from "vitest"

import { nextHub, type Point } from "./europe-route-walk"

const line: Point[] = [
  [0, 0],
  [1, 0],
  [5, 0],
  [10, 0],
]

test("picks the farthest unvisited point", () => {
  const { next } = nextHub(line, 0, new Set())
  assert.equal(next, 3)
})

test("skips visited points", () => {
  const { next, visited } = nextHub(line, 3, new Set([0]))
  assert.equal(next, 1)
  assert.deepEqual([...visited].sort(), [0, 3])
})

test("restarts the walk once every point was visited", () => {
  const { next, visited } = nextHub(line, 1, new Set([0, 2, 3]))
  assert.equal(next, 3)
  assert.deepEqual([...visited], [1])
})

test("walk never stalls and visits every point per round", () => {
  let current = 0
  let visited = new Set<number>()
  const seen = new Set<number>()
  for (let step = 0; step < 40; step++) {
    const r = nextHub(line, current, visited)
    assert.notEqual(r.next, current)
    seen.add(r.next)
    current = r.next
    visited = r.visited
  }
  assert.equal(seen.size, line.length)
})

test("handles degenerate input", () => {
  assert.equal(nextHub([[0, 0]], 0, new Set()).next, 0)
})
