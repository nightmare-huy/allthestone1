// =====================================================================================
//  All The Stone 1  -  the actual stone world
// -------------------------------------------------------------------------------------
//  Why this file exists:
//  `kubejs/data/minecraft/worldgen/noise_settings/overworld.json` turns the OVERWORLD
//  into solid stone, but a data file cannot change the generator stored inside an
//  already created level.dat. So the pack ships a dedicated dimension
//  (allthestone1:stone_world) that always generates with that noise settings id, sends
//  the player there on first join and keeps a small air pocket at the world origin.
//
//  The starter room is a 5x5x5 air pocket, exactly as designed:
//      x, z = -2 .. 2        (5 wide)
//      y    = 64 .. 68       (5 tall, the player spawns at y=64)
//      floor y=63, ceiling y=69
//  The whole shell is bedrock, so stone can never grow back into the room and the player
//  can never suffocate at spawn.
//
//  The room is built with /fill commands on purpose: they are version-proof, they need no
//  KubeJS block API and they apply atomically to the chunk.
// =====================================================================================

const STONE_DIM = "allthestone1:stone_world"

// the coordinates from the brief
const SPAWN = { x: 0, y: 64, z: 0 }

// replace this with `true` if you ever want the starter room in the OVERWORLD instead
// of the dedicated dimension (both use the same stone noise settings)
const BUILD_IN_OVERWORLD = false

// script-local counters, used instead of relying on any entity/server field
let scriptTicks = 0
let suffocationCheck = 0
let roomBuilt = false

/** Runs a command in the stone world (or the overworld, see BUILD_IN_OVERWORLD). */
function inStoneWorld(server, command) {
    if (BUILD_IN_OVERWORLD) {
        server.runCommandSilent(command)
    } else {
        server.runCommandSilent(`execute in ${STONE_DIM} run ${command}`)
    }
}

/** The stone world as a ServerLevel, or null when it is not loaded. */
function stoneWorld(server) {
    // LevelStem / dimension keys are resolved by id; getLevel accepts a string id in KubeJS
    return server.getLevel(STONE_DIM)
}

/** True when the stone dimension exists and can be written to. */
function stoneWorldReady(server) {
    return BUILD_IN_OVERWORLD || stoneWorld(server) != null
}

/**
 * Builds (or repairs) the starter room. Idempotent - safe to call on every login,
 * respawn and server start.
 */
function buildSpawnRoom(server) {
    if (!stoneWorldReady(server)) {
        console.warn(`[allthestone1] dimension ${STONE_DIM} is not loaded - check kubejs/data/allthestone1/dimension/stone_world.json`)
        return false
    }

    // 1. carve the 5x5x5 air pocket
    inStoneWorld(server, "fill -2 64 -2 2 68 2 minecraft:air")

    // 2. bedrock shell: floor, ceiling and the four walls
    inStoneWorld(server, "fill -3 63 -3 3 63 3 minecraft:bedrock")
    inStoneWorld(server, "fill -3 69 -3 3 69 3 minecraft:bedrock")
    inStoneWorld(server, "fill -3 64 -3 3 68 -3 minecraft:bedrock") // north wall
    inStoneWorld(server, "fill -3 64 3 3 68 3 minecraft:bedrock")   // south wall
    inStoneWorld(server, "fill -3 64 -3 -3 68 3 minecraft:bedrock")  // west wall
    inStoneWorld(server, "fill 3 64 -3 3 68 3 minecraft:bedrock")    // east wall

    // 3. a nicer floor: smooth stone with stone brick edging
    inStoneWorld(server, "fill -2 63 -2 2 63 2 minecraft:smooth_stone")
    inStoneWorld(server, "fill -2 63 -2 2 63 -2 minecraft:stone_bricks")
    inStoneWorld(server, "fill -2 63 2 2 63 2 minecraft:stone_bricks")
    inStoneWorld(server, "fill -2 63 -2 -2 63 2 minecraft:stone_bricks")
    inStoneWorld(server, "fill 2 63 -2 2 63 2 minecraft:stone_bricks")

    // 4. furniture: the torch from the brief, plus a crafting table and a furnace so the
    //    first recipes can be used immediately
    inStoneWorld(server, "setblock 0 64 -2 minecraft:torch")
    inStoneWorld(server, "setblock -2 64 1 minecraft:crafting_table")
    inStoneWorld(server, "setblock 2 64 1 minecraft:furnace")

    // 5. make sure nobody can be pushed out through a corner
    inStoneWorld(server, "fill -1 68 -1 1 68 1 minecraft:air")

    roomBuilt = true
    return true
}

/** Builds the room (if needed) and teleports the player into it. */
function sendToSpawnRoom(player) {
    const server = player.server
    if (!roomBuilt) {
        buildSpawnRoom(server)
    }
    if (BUILD_IN_OVERWORLD) {
        player.teleportTo(server.overworld, SPAWN.x + 0.5, SPAWN.y, SPAWN.z + 0.5, 180, 0)
    } else {
        player.teleportTo(STONE_DIM, SPAWN.x + 0.5, SPAWN.y, SPAWN.z + 0.5, 180, 0)
    }
}

// -------------------------------------------------------------------------------------
//  Server start: build the room and pin the world spawn inside it.
// -------------------------------------------------------------------------------------
ServerEvents.loaded(event => {
    const server = event.server
    roomBuilt = false
    scriptTicks = 0

    if (buildSpawnRoom(server)) {
        inStoneWorld(server, `setworldspawn ${SPAWN.x} ${SPAWN.y} ${SPAWN.z}`)
        inStoneWorld(server, "gamerule doDaylightCycle false")
        inStoneWorld(server, "gamerule spawnRadius 2")
        inStoneWorld(server, "gamerule keepInventory true")
        inStoneWorld(server, "gamerule doFireTick false")
        inStoneWorld(server, "gamerule doMobSpawning true")
    }
})

// -------------------------------------------------------------------------------------
//  Retry loop: on a brand new world the dimension may not exist yet during `loaded`.
// -------------------------------------------------------------------------------------
ServerEvents.tick(event => {
    scriptTicks++
    if (roomBuilt || scriptTicks % 40 !== 0) {
        return
    }
    const server = event.server
    if (buildSpawnRoom(server)) {
        inStoneWorld(server, `setworldspawn ${SPAWN.x} ${SPAWN.y} ${SPAWN.z}`)
    }
})

// -------------------------------------------------------------------------------------
//  First join  ->  stone world (+ the starter kit the Welcome quest chapter describes)
// -------------------------------------------------------------------------------------
PlayerEvents.loggedIn(event => {
    const player = event.player

    // "first_join" lives in the player's persistent data, so it survives death and relog
    const firstJoin = !player.persistentData.getBoolean("first_join")
    if (firstJoin) {
        player.persistentData.putBoolean("first_join", true)
    }

    // players that already existed before the pack was installed are moved as well
    const inStoneWorld = player.level.dimension.toString() === STONE_DIM
    if (!firstJoin && inStoneWorld) {
        return
    }

    sendToSpawnRoom(player)

    if (firstJoin) {
        player.tell(Text.gold("Добро пожаловать в All The Stone 1!"))
        player.tell(Text.gray("Вокруг тебя сплошной камень. Возьми молот, разбей камень на гальку, а гальку - в песок, и начни просеивать."))
        player.tell(Text.gray("Квест-бук лежит в инвентаре - там пошаговый гайд по Stone Age."))

        player.give(Item.of("ftbquests:book"))
        player.give(Item.of("exdeorum:wooden_hammer"))
        player.give(Item.of("exdeorum:string_mesh"))
        player.give(Item.of("minecraft:torch", 16))
    }
})

// -------------------------------------------------------------------------------------
//  Safety net: a player who somehow ends up inside stone is pulled back into the room.
// -------------------------------------------------------------------------------------
PlayerEvents.tick(event => {
    const player = event.player
    if (!BUILD_IN_OVERWORLD && player.level.dimension.toString() !== STONE_DIM) {
        return
    }
    // throttle: only look once per second
    suffocationCheck++
    if (suffocationCheck % 20 !== 0) {
        return
    }

    const feet = player.block
    const head = feet.offset(0, 1, 0)
    const solid = id => id !== "minecraft:air" && id !== "minecraft:bedrock"

    if (solid(feet.id) || solid(head.id)) {
        sendToSpawnRoom(player)
    }
})

// -------------------------------------------------------------------------------------
//  Death in the stone world -> respawn in the room (never on top of the stone ceiling).
// -------------------------------------------------------------------------------------
PlayerEvents.respawned(event => {
    const player = event.player
    if (BUILD_IN_OVERWORLD || player.level.dimension.toString() === STONE_DIM) {
        sendToSpawnRoom(player)
    }
})
