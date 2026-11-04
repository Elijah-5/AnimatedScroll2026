<script setup lang="ts">
import ImportPanel from '../ImportPanel.vue'
import StructuredLibrary from '../StructuredLibrary.vue'
import EntityActions from '../EntityActions.vue'
import {useStudio} from '../studioContext'
const s=useStudio();const emit=defineEmits(['replace','running'])
</script>
<template><div data-entity-key="material:main"><ImportPanel :project="s.p.value" studio @replace="emit('replace',$event)" @running="emit('running',$event)" @confirm-materials="s.confirm(s.rec('material','main'),false)"/><StructuredLibrary/></div></template>
